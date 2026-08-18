#!/usr/bin/env python3
"""Manage durable projects, their environments, and agent entry points."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote


MANIFEST_NAME = "project.toml"
PROJECT_SCHEMA = 1
PROJECTCTL_API_VERSION = 1
PROJECT_DIRECTORIES = (
    "sources/original",
    "sources/processed",
    "notebooks",
    "notes",
    "src",
    "figures",
    "artifacts",
)
SLUG_RE = re.compile(r"[^a-z0-9]+")
HARNESS_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
IGNORED_PROJECT_NAMES = {"templates"}


class ProjectError(ValueError):
    pass


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    title: str
    status: str
    root: Path
    managed: bool
    created_at: str | None
    manifest: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        return {
            "api_version": PROJECTCTL_API_VERSION,
            "schema": PROJECT_SCHEMA,
            "id": self.id,
            "name": self.name,
            "title": self.title,
            "status": self.status,
            "root": str(self.root),
            "managed": self.managed,
            "created_at": self.created_at,
            "environment": "nix" if project_flake(self) is not None else "host",
        }


def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


def projects_root() -> Path:
    return env_path("PROJECTS_ROOT", "/home/rishabh/Projects").resolve()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def slugify(raw: str) -> str:
    slug = SLUG_RE.sub("-", raw.lower()).strip("-")
    if not slug:
        raise ProjectError("project name must contain a letter or number")
    return slug[:80]


def implicit_project_id(root: Path) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"homelab-project:{root}"))


def require_string(value: Any, field: str, manifest_path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectError(f"{manifest_path}: {field} must be a non-empty string")
    return value.strip()


def load_project(root: Path) -> Project:
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        return Project(
            id=implicit_project_id(root),
            name=root.name,
            title=root.name,
            status="active",
            root=root,
            managed=False,
            created_at=None,
            manifest={},
        )

    try:
        with manifest_path.open("rb") as handle:
            manifest = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ProjectError(f"could not read {manifest_path}: {error}") from error

    if manifest.get("schema") != PROJECT_SCHEMA:
        raise ProjectError(
            f"{manifest_path}: unsupported project schema {manifest.get('schema')!r}"
        )
    project_id = require_string(manifest.get("id"), "id", manifest_path)
    try:
        uuid.UUID(project_id)
    except ValueError as error:
        raise ProjectError(f"{manifest_path}: id must be a UUID") from error
    name = require_string(manifest.get("name"), "name", manifest_path)
    if slugify(name) != name:
        raise ProjectError(f"{manifest_path}: name must be a lowercase project slug")
    title = require_string(manifest.get("title"), "title", manifest_path)
    status = require_string(manifest.get("status"), "status", manifest_path)
    if status not in {"active", "archived"}:
        raise ProjectError(f"{manifest_path}: status must be active or archived")
    created_at = manifest.get("created_at")
    if created_at is not None and not isinstance(created_at, str):
        raise ProjectError(f"{manifest_path}: created_at must be a string")
    return Project(
        id=project_id,
        name=name,
        title=title,
        status=status,
        root=root,
        managed=True,
        created_at=created_at,
        manifest=manifest,
    )


def project_directories() -> list[Path]:
    root = projects_root()
    if not root.is_dir():
        return []
    return sorted(
        (
            entry
            for entry in root.iterdir()
            if entry.is_dir()
            and not entry.is_symlink()
            and not entry.name.startswith(".")
            and entry.name not in IGNORED_PROJECT_NAMES
        ),
        key=lambda path: path.name.casefold(),
    )


def discover_projects(include_archived: bool = False) -> list[Project]:
    projects = [load_project(path) for path in project_directories()]
    seen_ids: dict[str, Path] = {}
    for project in projects:
        existing = seen_ids.get(project.id)
        if existing is not None:
            raise ProjectError(
                f"duplicate project id {project.id}: {existing} and {project.root}"
            )
        seen_ids[project.id] = project.root
    if not include_archived:
        projects = [project for project in projects if project.status == "active"]
    return projects


def path_project(reference: str) -> Path | None:
    root = projects_root()
    raw = Path(reference).expanduser()
    path_like = raw.is_absolute() or reference in {".", ".."} or "/" in reference
    candidate = raw.resolve() if path_like else (root / reference).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        if path_like:
            raise ProjectError(f"project path must be under {root}") from None
        return None
    if not relative.parts:
        raise ProjectError(
            f"choose a project beneath {root}, not the project root itself"
        )
    top_level = root / relative.parts[0]
    if not top_level.is_dir() or top_level.is_symlink():
        return None
    return top_level


def resolve_project(reference: str) -> Project:
    by_path = path_project(reference)
    if by_path is not None:
        return load_project(by_path)
    matches = [
        project
        for project in discover_projects(include_archived=True)
        if reference in {project.id, project.name}
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ProjectError(f"ambiguous project reference: {reference}")
    raise ProjectError(f"project not found: {reference}")


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def manifest_text(
    project_id: str,
    name: str,
    title: str,
    created_at: str,
    *,
    include_kernel: bool,
) -> str:
    lines = [
        f"schema = {PROJECT_SCHEMA}",
        f"id = {toml_string(project_id)}",
        f"name = {toml_string(name)}",
        f"title = {toml_string(title)}",
        'status = "active"',
        f"created_at = {toml_string(created_at)}",
        "",
        "[paths]",
        'sources_original = "sources/original"',
        'sources_processed = "sources/processed"',
        'notebooks = "notebooks"',
        'notes = "notes"',
        'source_code = "src"',
        'figures = "figures"',
        'artifacts = "artifacts"',
        "",
        "[environment]",
        'flake = "flake.nix"',
        "",
    ]
    if include_kernel:
        lines.extend(
            [
                "[jupyter]",
                f"kernel = {json.dumps(['python', '-m', 'ipykernel_launcher'])}",
                "",
            ]
        )
    return "\n".join(lines)


def flake_text(title: str) -> str:
    return f"""{{
  description = {toml_string(title + " project environment")};

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    {{ nixpkgs, ... }}:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${{system}};
      python = pkgs.python3.withPackages (ps: [ ps.ipykernel ]);
    in
    {{
      devShells.${{system}}.default = pkgs.mkShell {{
        packages = [
          python
          pkgs.git
          pkgs.just
        ];
      }};
    }};
}}
"""


def agents_text(title: str) -> str:
    return f"""# {title}

This is a durable project workspace. Keep project-specific source material,
notebooks, code, figures, and generated artifacts inside this directory.

Use the project Nix environment for commands and dependencies. Preserve
unrelated user changes and validate generated artifacts before replacing them.
"""


def gitignore_text() -> str:
    return """.direnv/
.ipynb_checkpoints/
__pycache__/
result
result-*
"""


def write_if_missing(path: Path, content: str) -> None:
    if path.exists() or path.is_symlink():
        return
    path.write_text(content, encoding="utf-8")


def scaffold_project(root: Path, project_id: str, name: str, title: str) -> None:
    for relative in PROJECT_DIRECTORIES:
        (root / relative).mkdir(parents=True, exist_ok=True)
    created_at = now_iso()
    manifest_path = root / MANIFEST_NAME
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ProjectError(f"project is already managed: {root}")
    has_existing_flake = (root / "flake.nix").exists()
    manifest_path.write_text(
        manifest_text(
            project_id,
            name,
            title,
            created_at,
            include_kernel=not has_existing_flake,
        ),
        encoding="utf-8",
    )
    write_if_missing(root / "flake.nix", flake_text(title))
    write_if_missing(root / "AGENTS.md", agents_text(title))
    write_if_missing(root / ".gitignore", gitignore_text())


def emit_project(project: Project, as_json: bool) -> None:
    if as_json:
        print(json.dumps(project.payload(), indent=2, sort_keys=True))
    else:
        print(project.root)


def replace_manifest_scalar(project: Project, field: str, value: str) -> Project:
    if not project.managed:
        raise ProjectError(f"initialize project metadata first: {project.root}")
    manifest_path = project.root / MANIFEST_NAME
    content = manifest_path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(field)}\s*=.*$", re.MULTILINE)
    replacement = f"{field} = {toml_string(value)}"
    updated, replacements = pattern.subn(replacement, content, count=1)
    if replacements != 1:
        raise ProjectError(f"{manifest_path}: missing {field}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{MANIFEST_NAME}.", dir=project.root
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(updated)
        temporary.chmod(manifest_path.stat().st_mode & 0o777)
        temporary.replace(manifest_path)
    finally:
        temporary.unlink(missing_ok=True)
    return load_project(project.root)


def command_create(args: argparse.Namespace) -> int:
    root = projects_root()
    root.mkdir(parents=True, exist_ok=True)
    name = slugify(args.name)
    title = args.title.strip() if args.title else args.name.strip()
    if not title:
        raise ProjectError("project title must not be empty")
    target = root / name
    if target.exists() or target.is_symlink():
        raise ProjectError(f"project path already exists: {target}")
    target.mkdir(mode=0o755)
    try:
        scaffold_project(target, str(uuid.uuid4()), name, title)
    except BaseException:
        shutil.rmtree(target)
        raise
    emit_project(load_project(target), args.json)
    return 0


def command_init(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    if project.managed:
        raise ProjectError(f"project is already managed: {project.root}")
    title = args.title.strip() if args.title else project.title
    if not title:
        raise ProjectError("project title must not be empty")
    # Keep the deterministic identity used while this directory was implicit.
    # T3 and other clients may already have durable references to it.
    scaffold_project(project.root, project.id, slugify(project.root.name), title)
    emit_project(load_project(project.root), args.json)
    return 0


def command_list(args: argparse.Namespace) -> int:
    projects = discover_projects(include_archived=args.all)
    if args.json:
        print(
            json.dumps(
                {
                    "api_version": PROJECTCTL_API_VERSION,
                    "schema": PROJECT_SCHEMA,
                    "projects": [project.payload() for project in projects],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if not projects:
        print(f"No projects found under {projects_root()}.")
        return 0
    print("NAME                     STATE      ENV   TITLE")
    for project in projects:
        state = project.status if project.managed else "implicit"
        environment = "nix" if project_flake(project) is not None else "host"
        print(f"{project.name[:24]:<24} {state:<10} {environment:<5} {project.title}")
    return 0


def command_capabilities(args: argparse.Namespace) -> int:
    payload = {
        "api_version": PROJECTCTL_API_VERSION,
        "project_schema": PROJECT_SCHEMA,
        "canonical_root": str(projects_root()),
        "operations": [
            "archive",
            "capabilities",
            "create",
            "env.check",
            "env.lock",
            "exec",
            "harnesses",
            "init",
            "jupyter",
            "list",
            "rename",
            "session",
            "shell",
            "show",
            "unarchive",
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"projectctl API {PROJECTCTL_API_VERSION}")
        print(f"canonical root: {payload['canonical_root']}")
        print("operations: " + ", ".join(payload["operations"]))
    return 0


def command_set_status(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    next_project = replace_manifest_scalar(project, "status", args.status)
    emit_project(next_project, args.json)
    return 0


def command_rename(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    title = args.title.strip()
    if not title:
        raise ProjectError("project title must not be empty")
    next_project = replace_manifest_scalar(project, "title", title)
    emit_project(next_project, args.json)
    return 0


def command_show(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    payload = project.payload()
    payload["jupyter_url"] = jupyter_url(project)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for key in (
            "id",
            "name",
            "title",
            "status",
            "root",
            "managed",
            "environment",
            "jupyter_url",
        ):
            print(f"{key}: {payload[key]}")
    return 0


def environment_table(project: Project) -> dict[str, Any]:
    value = project.manifest.get("environment", {})
    return value if isinstance(value, dict) else {}


def project_flake(project: Project) -> Path | None:
    table = environment_table(project)
    configured = table.get("flake", "flake.nix")
    if not isinstance(configured, str) or not configured:
        return None
    candidate = (project.root / configured).resolve()
    try:
        candidate.relative_to(project.root)
    except ValueError:
        raise ProjectError(f"project flake must remain under {project.root}") from None
    return candidate if candidate.is_file() else None


def nix_bin() -> str:
    return os.environ.get("PROJECTCTL_NIX_BIN", "nix")


def nix_flake_reference(project: Project) -> str:
    flake = project_flake(project)
    if flake is None:
        raise ProjectError(f"project has no Nix environment: {project.root}")
    if flake.name != "flake.nix":
        raise ProjectError(
            "first-pass project environments require flake.nix at the project root"
        )
    return f"path:{project.root}"


def project_command(
    project: Project, command: list[str], direct: bool = False
) -> list[str]:
    if direct or project_flake(project) is None:
        return command
    return [nix_bin(), "develop", nix_flake_reference(project), "--command", *command]


def exec_command(
    project: Project,
    command: list[str],
    direct: bool = False,
    cwd: str | None = None,
) -> int:
    if not command:
        raise ProjectError("a command is required")
    os.chdir(validated_execution_root(project, cwd))
    resolved = project_command(project, command, direct=direct)
    os.execvpe(resolved[0], resolved, os.environ.copy())
    return 0


def validated_execution_root(project: Project, requested: str | None) -> Path:
    if requested is None:
        return project.root
    candidate = Path(requested).expanduser().resolve()
    try:
        candidate.relative_to(project.root)
    except ValueError:
        raise ProjectError(
            f"execution directory must remain under project root {project.root}"
        ) from None
    if not candidate.is_dir():
        raise ProjectError(f"execution directory does not exist: {candidate}")
    return candidate


def strip_separator(arguments: list[str]) -> list[str]:
    return arguments[1:] if arguments and arguments[0] == "--" else arguments


def harness_config() -> dict[str, list[str]]:
    raw = os.environ.get(
        "PROJECTCTL_HARNESSES_JSON",
        json.dumps({"codex": ["codex", "-C", "{project}"], "pi": ["pi"]}),
    )
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProjectError("PROJECTCTL_HARNESSES_JSON is invalid") from error
    if not isinstance(decoded, dict):
        raise ProjectError("PROJECTCTL_HARNESSES_JSON must be an object")
    result: dict[str, list[str]] = {}
    for name, command in decoded.items():
        if not isinstance(name, str) or HARNESS_RE.fullmatch(name) is None:
            raise ProjectError(f"invalid harness name: {name!r}")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(item, str) for item in command)
        ):
            raise ProjectError(f"harness {name} must contain a non-empty command array")
        result[name] = command
    return result


def command_harnesses(args: argparse.Namespace) -> int:
    harnesses = harness_config()
    payload = [
        {
            "name": name,
            "command": command,
            "available": Path(command[0]).is_file()
            if Path(command[0]).is_absolute()
            else shutil.which(command[0]) is not None,
        }
        for name, command in sorted(harnesses.items())
    ]
    if args.json:
        print(json.dumps({"harnesses": payload}, indent=2, sort_keys=True))
    else:
        for item in payload:
            status = "ready" if item["available"] else "missing"
            print(f"{item['name']:<16} {status:<8} {' '.join(item['command'])}")
    return 0


def command_session(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    harnesses = harness_config()
    template = harnesses.get(args.harness)
    if template is None:
        raise ProjectError(
            f"unknown harness {args.harness!r}; use 'projectctl harnesses'"
        )
    command = [item.replace("{project}", str(project.root)) for item in template]
    command.extend(strip_separator(args.arguments))
    return exec_command(project, command, direct=args.direct, cwd=args.cwd)


def command_exec(args: argparse.Namespace) -> int:
    return exec_command(
        resolve_project(args.project),
        strip_separator(args.arguments),
        direct=args.direct,
        cwd=args.cwd,
    )


def command_shell(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    reference = nix_flake_reference(project)
    command = [nix_bin(), "develop", reference, *strip_separator(args.arguments)]
    os.chdir(project.root)
    os.execvpe(command[0], command, os.environ.copy())
    return 0


def command_env_check(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    command = [
        nix_bin(),
        "flake",
        "check",
        "--no-write-lock-file",
        nix_flake_reference(project),
    ]
    os.chdir(project.root)
    os.execvpe(command[0], command, os.environ.copy())
    return 0


def command_env_lock(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    command = [nix_bin(), "flake", "lock", nix_flake_reference(project)]
    os.chdir(project.root)
    os.execvpe(command[0], command, os.environ.copy())
    return 0


def jupyter_url(project: Project) -> str:
    base = os.environ.get(
        "PROJECTCTL_JUPYTER_URL", "https://lab.internal.therealrishabh.com"
    ).rstrip("/")
    jupyter_root = env_path("PROJECTCTL_JUPYTER_ROOT", "/").resolve()
    try:
        relative = project.root.relative_to(jupyter_root)
    except ValueError:
        raise ProjectError(
            f"project is outside the configured Jupyter root: {project.root}"
        ) from None
    encoded = quote(relative.as_posix(), safe="/")
    return f"{base}/lab/tree/{encoded}"


def jupyter_kernel_command(project: Project) -> list[str] | None:
    table = project.manifest.get("jupyter", {})
    configured = table.get("kernel") if isinstance(table, dict) else None
    if configured is None:
        return None
    if (
        not isinstance(configured, list)
        or not configured
        or not all(isinstance(item, str) for item in configured)
    ):
        raise ProjectError(
            f"{project.root / MANIFEST_NAME}: jupyter.kernel must be a command array"
        )
    return configured


def register_jupyter_kernel(project: Project) -> str | None:
    if project_flake(project) is None or jupyter_kernel_command(project) is None:
        return None
    kernel_root = env_path(
        "PROJECTCTL_JUPYTER_KERNEL_DIR", "/srv/state/jupyterlab/data/kernels"
    )
    kernel_name = f"project-{project.id.replace('-', '')[:16]}"
    target = kernel_root / kernel_name
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    executable = os.environ.get(
        "PROJECTCTL_SELF", "/run/current-system/sw/bin/projectctl"
    )
    payload = {
        "argv": [executable, "kernel", project.id, "--", "-f", "{connection_file}"],
        "display_name": f"Python ({project.title})",
        "language": "python",
        "metadata": {"debugger": True, "project_id": project.id},
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".kernel.", suffix=".json", dir=target
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.chmod(0o600)
        temporary.replace(target / "kernel.json")
    finally:
        temporary.unlink(missing_ok=True)
    return kernel_name


def command_jupyter(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    kernel = None if args.no_kernel else register_jupyter_kernel(project)
    url = jupyter_url(project)
    if args.json:
        print(
            json.dumps(
                {"project": project.payload(), "url": url, "kernel": kernel},
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(url)
    return 0


def command_kernel(args: argparse.Namespace) -> int:
    project = resolve_project(args.project)
    kernel_command = jupyter_kernel_command(project)
    if kernel_command is None:
        raise ProjectError(f"project has no Jupyter kernel command: {project.root}")
    return exec_command(
        project,
        [*kernel_command, *strip_separator(args.arguments)],
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="projectctl", description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    capabilities = commands.add_parser(
        "capabilities", help="show the versioned project-control API"
    )
    capabilities.add_argument("--json", action="store_true")
    capabilities.set_defaults(func=command_capabilities)

    create = commands.add_parser("create", help="create a durable managed project")
    create.add_argument("name")
    create.add_argument("--title")
    create.add_argument("--json", action="store_true")
    create.set_defaults(func=command_create)

    init = commands.add_parser(
        "init", help="add a manifest and standard layout to an existing project"
    )
    init.add_argument("project")
    init.add_argument("--title")
    init.add_argument("--json", action="store_true")
    init.set_defaults(func=command_init)

    list_command = commands.add_parser(
        "list", help="list projects under the canonical root"
    )
    list_command.add_argument(
        "--all", action="store_true", help="include archived managed projects"
    )
    list_command.add_argument("--json", action="store_true")
    list_command.set_defaults(func=command_list)

    show = commands.add_parser("show", help="show resolved project metadata")
    show.add_argument("project")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=command_show)

    rename = commands.add_parser("rename", help="change a managed project's title")
    rename.add_argument("project")
    rename.add_argument("title")
    rename.add_argument("--json", action="store_true")
    rename.set_defaults(func=command_rename)

    for command_name, status in (("archive", "archived"), ("unarchive", "active")):
        lifecycle = commands.add_parser(
            command_name, help=f"mark a managed project {status}"
        )
        lifecycle.add_argument("project")
        lifecycle.add_argument("--json", action="store_true")
        lifecycle.set_defaults(func=command_set_status, status=status)

    harnesses = commands.add_parser("harnesses", help="list configured agent harnesses")
    harnesses.add_argument("--json", action="store_true")
    harnesses.set_defaults(func=command_harnesses)

    session = commands.add_parser(
        "session", help="launch an agent session in a project"
    )
    session.add_argument(
        "--direct", action="store_true", help="skip the project Nix environment"
    )
    session.add_argument("--cwd", help="run from a directory inside the project")
    session.add_argument("project")
    session.add_argument("harness", nargs="?", default="codex")
    session.add_argument("arguments", nargs=argparse.REMAINDER)
    session.set_defaults(func=command_session)

    execute = commands.add_parser("exec", help="run a command in a project environment")
    execute.add_argument(
        "--direct", action="store_true", help="skip the project Nix environment"
    )
    execute.add_argument("--cwd", help="run from a directory inside the project")
    execute.add_argument("project")
    execute.add_argument("arguments", nargs=argparse.REMAINDER)
    execute.set_defaults(func=command_exec)

    shell = commands.add_parser("shell", help="enter a project's Nix development shell")
    shell.add_argument("project")
    shell.add_argument("arguments", nargs=argparse.REMAINDER)
    shell.set_defaults(func=command_shell)

    environment = commands.add_parser("env", help="manage a project's Nix environment")
    environment_commands = environment.add_subparsers(dest="env_command", required=True)
    env_check = environment_commands.add_parser(
        "check", help="evaluate and check the project flake"
    )
    env_check.add_argument("project")
    env_check.set_defaults(func=command_env_check)
    env_lock = environment_commands.add_parser(
        "lock", help="create or update the project flake lock"
    )
    env_lock.add_argument("project")
    env_lock.set_defaults(func=command_env_lock)

    jupyter = commands.add_parser(
        "jupyter", help="print the JupyterLab URL for a project"
    )
    jupyter.add_argument("project")
    jupyter.add_argument("--no-kernel", action="store_true")
    jupyter.add_argument("--json", action="store_true")
    jupyter.set_defaults(func=command_jupyter)

    kernel = commands.add_parser("kernel", help=argparse.SUPPRESS)
    kernel.add_argument("project")
    kernel.add_argument("arguments", nargs=argparse.REMAINDER)
    kernel.set_defaults(func=command_kernel)

    return root


def main() -> int:
    try:
        args = parser().parse_args()
        return int(args.func(args))
    except (OSError, ProjectError) as error:
        print(f"projectctl: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
