#!/usr/bin/env python3
"""Cross-harness global agent skill manager for Homelab.

Manages a hybrid two-layer global skills store:
  1. Declarative skills built by Nix from Homelab (components/skills/declarative.nix)
  2. Mutable user-installed skills in $SKILLS_STATE/installed (tracked in manifest.json)

Materializes active skills into each agent harness's native user skill directory
(Codex, Claude Code, Antigravity) while leaving harness-owned entries untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MAX_SKILL_MD_BYTES = 1_000_000
VALID_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
GITHUB_SHORTHAND_RE = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)(?:/(?P<subpath>.+))?$"
)
SKIP_DIR_NAMES = frozenset({".git", "__pycache__"})


class SkillError(Exception):
    """User-facing CLI error."""


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    skill_md_path: Path
    size_bytes: int


@dataclass(frozen=True)
class ActiveSkill:
    name: str
    origin: str  # "declarative" | "installed"
    overrides_declarative: bool
    source_dir: Path
    metadata: SkillMetadata
    digest: str
    record: dict[str, Any]


@dataclass(frozen=True)
class TargetSpec:
    label: str
    path: Path


@dataclass(frozen=True)
class ParsedSource:
    kind: str  # "local" | "git"
    raw: str
    local_path: Path | None = None
    url: str | None = None
    owner: str | None = None
    repo: str | None = None
    ref: str | None = None
    subpath: str | None = None


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_state_dir() -> Path:
    return Path(os.environ.get("SKILLS_STATE", "/srv/state/skills")).expanduser()


def get_declarative_dir() -> Path | None:
    raw = os.environ.get("SKILLS_DECLARATIVE_DIR", "").strip()
    if not raw:
        return None
    return Path(raw)


def get_declarative_meta() -> dict[str, dict[str, Any]]:
    raw = os.environ.get("SKILLS_DECLARATIVE_META", "").strip()
    if not raw:
        return {}
    path = Path(raw)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def get_targets() -> list[TargetSpec]:
    raw = os.environ.get(
        "SKILLS_TARGETS",
        "codex=/srv/state/codex/skills:"
        "claude=/srv/state/claude/skills:"
        "antigravity=/srv/state/antigravity/config/skills",
    )
    targets: list[TargetSpec] = []
    for item in raw.split(":"):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            label, path_str = item.split("=", 1)
            targets.append(TargetSpec(label=label.strip(), path=Path(path_str.strip()).expanduser()))
        else:
            p = Path(item).expanduser()
            targets.append(TargetSpec(label=p.parent.name or str(p), path=p))
    return targets


def get_extra_scan_dirs() -> list[Path]:
    raw = os.environ.get("SKILLS_EXTRA_SCAN_DIRS", "/home/rishabh/.agents/skills")
    result: list[Path] = []
    for item in raw.split(":"):
        item = item.strip()
        if item:
            result.append(Path(item).expanduser())
    return result


def get_t3_antigravity_root() -> Path:
    return Path(
        os.environ.get(
            "SKILLS_T3_ANTIGRAVITY_ROOT",
            "/srv/state/t3code/userdata/providers/antigravity",
        )
    ).expanduser()


def _unquote_yaml_scalar(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] == '"':
        # Find closing unescaped double quote
        out: list[str] = []
        i = 1
        while i < len(value):
            ch = value[i]
            if ch == "\\" and i + 1 < len(value):
                nxt = value[i + 1]
                escapes = {
                    '"': '"',
                    "\\": "\\",
                    "/": "/",
                    "n": "\n",
                    "r": "\r",
                    "t": "\t",
                }
                out.append(escapes.get(nxt, nxt))
                i += 2
                continue
            if ch == '"':
                return "".join(out)
            out.append(ch)
            i += 1
        raise SkillError("Unterminated double-quoted string in SKILL.md frontmatter")
    if value[0] == "'":
        out = []
        i = 1
        while i < len(value):
            if value[i] == "'":
                if i + 1 < len(value) and value[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out)
            out.append(value[i])
            i += 1
        raise SkillError("Unterminated single-quoted string in SKILL.md frontmatter")
    # Unquoted scalar: strip trailing inline comment if preceded by whitespace
    comment_idx = value.find(" #")
    if comment_idx != -1:
        value = value[:comment_idx].rstrip()
    return value


def parse_yaml_frontmatter(text: str) -> dict[str, str]:
    """Parse top-level scalar fields from YAML frontmatter without external deps."""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError("SKILL.md must begin with YAML frontmatter delimited by '---'")
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise SkillError("SKILL.md YAML frontmatter is missing a closing '---'")

    fm_lines = lines[1:end_idx]
    fields: dict[str, str] = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if line[0].isspace():
            # Nested mapping/list line under another key; skip
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, rest = line.split(":", 1)
        key = key.strip()
        rest_stripped = rest.strip()
        if rest_stripped in {"|", "|-", "|+", ">", ">-", ">+"}:
            style = rest_stripped[0]
            chomp = rest_stripped[1:] if len(rest_stripped) > 1 else ""
            block_lines: list[str] = []
            i += 1
            indent: int | None = None
            while i < len(fm_lines):
                bline = fm_lines[i]
                if not bline.strip():
                    block_lines.append("")
                    i += 1
                    continue
                leading = len(bline) - len(bline.lstrip(" "))
                if leading == 0:
                    break
                if indent is None:
                    indent = leading
                if leading < indent:
                    break
                block_lines.append(bline[indent:])
                i += 1
            while block_lines and block_lines[-1] == "" and chomp != "+":
                block_lines.pop()
            if style == ">":
                joined = " ".join(part.strip() for part in block_lines if part.strip())
            else:
                joined = "\n".join(block_lines)
            fields[key] = joined
            continue
        fields[key] = _unquote_yaml_scalar(rest)
        i += 1
    return fields


def validate_skill_dir(skill_dir: Path, expected_name: str | None = None) -> SkillMetadata:
    if not skill_dir.is_dir():
        raise SkillError(f"Skill directory does not exist: {skill_dir}")
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SkillError(f"Missing SKILL.md in {skill_dir}")
    size = skill_md.stat().st_size
    if size > MAX_SKILL_MD_BYTES:
        raise SkillError(
            f"{skill_md} is {size} bytes, exceeding Antigravity's {MAX_SKILL_MD_BYTES}-byte limit"
        )
    text = skill_md.read_text(encoding="utf-8")
    fields = parse_yaml_frontmatter(text)
    name = fields.get("name", "")
    description = fields.get("description", "").strip()
    if not name or name != name.strip():
        raise SkillError(f"{skill_md} frontmatter must define a non-empty trimmed 'name'")
    if not VALID_SKILL_NAME_RE.match(name) or name in {".", ".."}:
        raise SkillError(
            f"Invalid skill name '{name}' in {skill_md}; expected alphanumeric, '.', '_', or '-'"
        )
    if not description:
        raise SkillError(f"{skill_md} frontmatter must define a non-empty 'description'")
    if expected_name is not None and name != expected_name:
        raise SkillError(
            f"Skill directory '{expected_name}' does not match SKILL.md frontmatter name '{name}'"
        )
    return SkillMetadata(
        name=name,
        description=description,
        skill_md_path=skill_md,
        size_bytes=size,
    )


def hash_directory(root: Path) -> str:
    """Compute a deterministic SHA-256 digest of a skill directory's contents."""
    hasher = hashlib.sha256()
    entries: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIR_NAMES)
        for fname in sorted(filenames):
            full = Path(dirpath) / fname
            rel = full.relative_to(root).as_posix()
            entries.append((rel, full))
    entries.sort(key=lambda item: item[0])
    for rel, full in entries:
        st = full.stat()
        exec_bit = "x" if (st.st_mode & 0o111) else "-"
        hasher.update(f"F:{rel}:{exec_bit}\0".encode("utf-8"))
        with full.open("rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
        hasher.update(b"\0")
    return hasher.hexdigest()


def copy_skill_tree(src: Path, dst: Path) -> None:
    """Copy a skill tree into dst with normalized user-writable permissions."""
    dst.mkdir(parents=True, exist_ok=True)
    os.chmod(dst, 0o755)
    for dirpath, dirnames, filenames in os.walk(src, followlinks=True):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIR_NAMES)
        rel_dir = Path(dirpath).relative_to(src)
        target_dir = dst / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(target_dir, 0o755)
        for fname in sorted(filenames):
            src_file = Path(dirpath) / fname
            dst_file = target_dir / fname
            shutil.copyfile(src_file, dst_file)
            src_mode = src_file.stat().st_mode
            os.chmod(dst_file, 0o755 if (src_mode & 0o111) else 0o644)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def load_json_file(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return json.loads(json.dumps(default))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SkillError(f"Expected JSON object in {path}")
    return data


def load_manifest(state_dir: Path) -> dict[str, Any]:
    data = load_json_file(state_dir / "manifest.json", {"version": 1, "skills": {}})
    if not isinstance(data.get("skills"), dict):
        data["skills"] = {}
    return data


def save_manifest(state_dir: Path, manifest: dict[str, Any]) -> None:
    manifest["version"] = 1
    atomic_write_json(state_dir / "manifest.json", manifest)


def load_managed(state_dir: Path) -> dict[str, Any]:
    data = load_json_file(state_dir / "managed.json", {"version": 1, "targets": {}})
    if not isinstance(data.get("targets"), dict):
        data["targets"] = {}
    return data


def save_managed(state_dir: Path, managed: dict[str, Any]) -> None:
    managed["version"] = 1
    atomic_write_json(state_dir / "managed.json", managed)


def replace_dir_atomically(src: Path, dest: Path) -> None:
    """Replace dest with a freshly materialized copy of src."""
    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    token = f"{os.getpid()}-{secrets.token_hex(4)}"
    staging = parent / f".homelab-skills-new-{dest.name}-{token}"
    backup = parent / f".homelab-skills-old-{dest.name}-{token}"
    try:
        copy_skill_tree(src, staging)
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
            os.rename(staging, dest)
        elif dest.exists():
            os.rename(dest, backup)
            try:
                os.rename(staging, dest)
            except OSError:
                os.rename(backup, dest)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            os.rename(staging, dest)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def collect_declarative_skills() -> dict[str, tuple[Path, SkillMetadata, dict[str, Any]]]:
    decl_dir = get_declarative_dir()
    if decl_dir is None or not decl_dir.is_dir():
        return {}
    meta_map = get_declarative_meta()
    skills: dict[str, tuple[Path, SkillMetadata, dict[str, Any]]] = {}
    for entry in sorted(decl_dir.iterdir(), key=lambda p: p.name):
        if entry.name.startswith("."):
            continue
        if not entry.is_dir():
            continue
        metadata = validate_skill_dir(entry, expected_name=entry.name)
        record = meta_map.get(entry.name, {})
        if not isinstance(record, dict):
            record = {}
        skills[entry.name] = (entry, metadata, record)
    return skills


def collect_installed_skills(
    state_dir: Path, manifest: dict[str, Any]
) -> dict[str, tuple[Path, SkillMetadata, dict[str, Any]]]:
    installed_root = state_dir / "installed"
    if not installed_root.is_dir():
        return {}
    skills: dict[str, tuple[Path, SkillMetadata, dict[str, Any]]] = {}
    records = manifest.get("skills", {})
    for entry in sorted(installed_root.iterdir(), key=lambda p: p.name):
        if entry.name.startswith("."):
            continue
        if not entry.is_dir():
            continue
        metadata = validate_skill_dir(entry, expected_name=entry.name)
        record = records.get(entry.name, {})
        if not isinstance(record, dict):
            record = {}
        skills[entry.name] = (entry, metadata, record)
    return skills


def collect_active_skills(state_dir: Path) -> dict[str, ActiveSkill]:
    manifest = load_manifest(state_dir)
    declarative = collect_declarative_skills()
    installed = collect_installed_skills(state_dir, manifest)

    active: dict[str, ActiveSkill] = {}
    for name, (src_dir, meta, record) in declarative.items():
        active[name] = ActiveSkill(
            name=name,
            origin="declarative",
            overrides_declarative=False,
            source_dir=src_dir,
            metadata=meta,
            digest=hash_directory(src_dir),
            record=record,
        )
    for name, (src_dir, meta, record) in installed.items():
        active[name] = ActiveSkill(
            name=name,
            origin="installed",
            overrides_declarative=name in declarative,
            source_dir=src_dir,
            metadata=meta,
            digest=hash_directory(src_dir),
            record=record,
        )
    return dict(sorted(active.items()))


def inspect_target_status(
    target: TargetSpec, skill: ActiveSkill, managed_target: dict[str, str]
) -> str:
    dest = target.path / skill.name
    if not dest.exists() and not dest.is_symlink():
        return "missing"
    if skill.name not in managed_target:
        return "conflict"
    if dest.is_symlink() or not dest.is_dir():
        return "stale"
    try:
        current_digest = hash_directory(dest)
    except OSError:
        return "stale"
    return "ok" if current_digest == skill.digest else "stale"


def sync_all(state_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    active = collect_active_skills(state_dir)
    managed = load_managed(state_dir)
    targets = get_targets()

    summary: dict[str, Any] = {
        "active": sorted(active.keys()),
        "targets": {},
        "conflicts": [],
    }

    for target in targets:
        target_key = str(target.path)
        managed_target = managed["targets"].get(target_key, {})
        if not isinstance(managed_target, dict):
            managed_target = {}
        new_managed_target = dict(managed_target)

        created: list[str] = []
        updated: list[str] = []
        removed: list[str] = []
        unchanged: list[str] = []
        conflicts: list[str] = []

        if not dry_run:
            target.path.mkdir(parents=True, exist_ok=True)

        # Remove skills that were previously managed here but are no longer active
        for old_name in sorted(list(managed_target.keys())):
            if old_name in active:
                continue
            dest = target.path / old_name
            if dest.is_symlink() or dest.is_file():
                if not dry_run:
                    dest.unlink()
                removed.append(old_name)
            elif dest.is_dir():
                if not dry_run:
                    shutil.rmtree(dest)
                removed.append(old_name)
            new_managed_target.pop(old_name, None)

        # Install/update active skills
        for name, skill in active.items():
            dest = target.path / name
            was_managed = name in managed_target
            exists = dest.exists() or dest.is_symlink()

            if exists and not was_managed:
                conflicts.append(name)
                summary["conflicts"].append({"target": target.label, "path": str(dest), "skill": name})
                continue

            if exists and dest.is_dir() and not dest.is_symlink():
                try:
                    current_digest = hash_directory(dest)
                except OSError:
                    current_digest = ""
                if current_digest == skill.digest:
                    unchanged.append(name)
                    new_managed_target[name] = skill.digest
                    continue
                if not dry_run:
                    replace_dir_atomically(skill.source_dir, dest)
                updated.append(name)
                new_managed_target[name] = skill.digest
            else:
                if not dry_run:
                    replace_dir_atomically(skill.source_dir, dest)
                if was_managed:
                    updated.append(name)
                else:
                    created.append(name)
                new_managed_target[name] = skill.digest

        managed["targets"][target_key] = new_managed_target
        summary["targets"][target.label] = {
            "path": str(target.path),
            "created": created,
            "updated": updated,
            "removed": removed,
            "unchanged": unchanged,
            "conflicts": conflicts,
        }

    if not dry_run:
        state_dir.mkdir(parents=True, exist_ok=True)
        save_managed(state_dir, managed)

    return summary


def parse_source(raw: str, ref_override: str | None = None) -> ParsedSource:
    candidate_path = Path(raw).expanduser()
    if candidate_path.exists():
        return ParsedSource(kind="local", raw=raw, local_path=candidate_path.resolve())

    if raw.startswith("github:"):
        rest = raw[len("github:") :].strip("/")
        match = GITHUB_SHORTHAND_RE.match(rest)
        if not match:
            raise SkillError(f"Invalid github: source '{raw}'; expected github:owner/repo[/subpath]")
        owner = match.group("owner")
        repo = match.group("repo")
        subpath = match.group("subpath")
        if subpath and subpath.endswith("/SKILL.md"):
            subpath = subpath[: -len("/SKILL.md")] or None
        return ParsedSource(
            kind="git",
            raw=raw,
            url=f"https://github.com/{owner}/{repo}.git",
            owner=owner,
            repo=repo,
            ref=ref_override,
            subpath=subpath.strip("/") if subpath else None,
        )

    parsed_url = urlparse(raw)
    if parsed_url.scheme in {"http", "https"} and parsed_url.netloc in {
        "github.com",
        "www.github.com",
    }:
        parts = [p for p in parsed_url.path.split("/") if p]
        if len(parts) < 2:
            raise SkillError(f"Invalid GitHub URL: {raw}")
        owner = parts[0]
        repo = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
        ref = ref_override
        subpath: str | None = None
        if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
            if ref is None:
                ref = parts[3]
            sub_parts = parts[4:]
            if parts[2] == "blob" and sub_parts and sub_parts[-1].lower() == "skill.md":
                sub_parts = sub_parts[:-1]
            subpath = "/".join(sub_parts) or None
        elif len(parts) > 2:
            subpath = "/".join(parts[2:])
            if subpath.lower().endswith("/skill.md"):
                subpath = subpath[: -len("/SKILL.md")] or None
        return ParsedSource(
            kind="git",
            raw=raw,
            url=f"https://github.com/{owner}/{repo}.git",
            owner=owner,
            repo=repo,
            ref=ref,
            subpath=subpath,
        )

    if (
        parsed_url.scheme in {"http", "https", "ssh", "file", "git"}
        or raw.startswith("git@")
        or raw.endswith(".git")
    ):
        return ParsedSource(kind="git", raw=raw, url=raw, ref=ref_override)

    match = GITHUB_SHORTHAND_RE.match(raw.strip("/"))
    if match and not raw.startswith((".", "/")):
        owner = match.group("owner")
        repo = match.group("repo")
        subpath = match.group("subpath")
        if subpath and subpath.endswith("/SKILL.md"):
            subpath = subpath[: -len("/SKILL.md")] or None
        return ParsedSource(
            kind="git",
            raw=raw,
            url=f"https://github.com/{owner}/{repo}.git",
            owner=owner,
            repo=repo,
            ref=ref_override,
            subpath=subpath.strip("/") if subpath else None,
        )

    raise SkillError(f"Source not found as local path and not a recognized git/GitHub reference: {raw}")


def run_git(args: list[str], cwd: Path | None = None) -> str:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or f"git exited with {proc.returncode}"
        raise SkillError(f"git {' '.join(args)} failed: {msg}")
    return proc.stdout.strip()


def clone_git_repo(url: str, dest: Path, ref: str | None) -> tuple[str, str | None]:
    """Clone url into dest at ref (if given), returning (commit_sha, resolved_ref)."""
    if ref:
        # Try shallow branch/tag clone first; fall back to full clone + checkout for raw SHAs
        try:
            run_git(["clone", "--depth", "1", "--branch", ref, "--", url, str(dest)])
        except SkillError:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            run_git(["clone", "--", url, str(dest)])
            run_git(["checkout", "--detach", ref], cwd=dest)
        rev = run_git(["rev-parse", "HEAD"], cwd=dest)
        return rev, ref

    run_git(["clone", "--depth", "1", "--", url, str(dest)])
    rev = run_git(["rev-parse", "HEAD"], cwd=dest)
    try:
        branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest)
        resolved_ref = None if branch == "HEAD" else branch
    except SkillError:
        resolved_ref = None
    return rev, resolved_ref


def discover_skills_in_tree(root: Path) -> list[tuple[Path, str | None, SkillMetadata]]:
    """Find skill directories inside root (at root, depth 1, or under skills/*)."""
    found: list[tuple[Path, str | None, SkillMetadata]] = []
    seen_dirs: set[Path] = set()

    def check_dir(candidate: Path) -> None:
        resolved = candidate.resolve()
        if resolved in seen_dirs or not candidate.is_dir():
            return
        if not (candidate / "SKILL.md").is_file():
            return
        meta = validate_skill_dir(candidate)
        seen_dirs.add(resolved)
        rel = candidate.relative_to(root).as_posix()
        found.append((candidate, None if rel == "." else rel, meta))

    check_dir(root)
    if found:
        return found

    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        check_dir(entry)
        if entry.name == "skills":
            for child in sorted(entry.iterdir(), key=lambda p: p.name):
                if child.name.startswith(".") or not child.is_dir():
                    continue
                check_dir(child)

    found.sort(key=lambda item: item[2].name)
    return found


def select_skills_from_root(
    root: Path,
    subpath: str | None,
    skill_selector: str | None,
    install_all: bool,
) -> list[tuple[Path, str | None, SkillMetadata]]:
    if subpath:
        target = (root / subpath).resolve()
        root_resolved = root.resolve()
        if root_resolved != target and root_resolved not in target.parents:
            raise SkillError(f"Subpath escapes repository root: {subpath}")
        meta = validate_skill_dir(target)
        return [(target, subpath.strip("/"), meta)]

    if skill_selector:
        for candidate_rel in (skill_selector, f"skills/{skill_selector}"):
            candidate = (root / candidate_rel).resolve()
            root_resolved = root.resolve()
            if (root_resolved == candidate or root_resolved in candidate.parents) and (
                candidate / "SKILL.md"
            ).is_file():
                meta = validate_skill_dir(candidate)
                return [(candidate, candidate_rel.strip("/"), meta)]
        discovered = discover_skills_in_tree(root)
        matches = [item for item in discovered if item[2].name == skill_selector]
        if matches:
            return matches
        available = ", ".join(item[2].name for item in discovered) or "(none)"
        raise SkillError(f"Skill '{skill_selector}' not found. Available: {available}")

    discovered = discover_skills_in_tree(root)
    if not discovered:
        raise SkillError(f"No valid skills (containing SKILL.md) found in {root}")
    if len(discovered) == 1 or install_all:
        return discovered

    names = ", ".join(item[2].name for item in discovered)
    raise SkillError(
        f"Multiple skills found ({names}). Re-run with --skill <name> or --all."
    )


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser()
    expected = args.expected_name
    meta = validate_skill_dir(path, expected_name=expected)
    print(f"ok: {meta.name} ({meta.size_bytes} bytes)")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    state_dir = get_state_dir()
    active = collect_active_skills(state_dir)
    managed = load_managed(state_dir)
    targets = get_targets()

    items: list[dict[str, Any]] = []
    for name, skill in active.items():
        statuses = {}
        for target in targets:
            managed_target = managed["targets"].get(str(target.path), {})
            statuses[target.label] = inspect_target_status(target, skill, managed_target)
        items.append(
            {
                "name": name,
                "origin": skill.origin,
                "overridesDeclarative": skill.overrides_declarative,
                "description": skill.metadata.description,
                "source": skill.record.get("source"),
                "rev": skill.record.get("rev"),
                "digest": skill.digest[:12],
                "targets": statuses,
            }
        )

    if args.json:
        print(json.dumps(items, indent=2))
        return 0

    if not items:
        print("No active skills.")
        return 0

    for item in items:
        origin_tag = item["origin"]
        if item["overridesDeclarative"]:
            origin_tag = "installed (overrides declarative)"
        rev_part = f" @ {item['rev'][:10]}" if item.get("rev") else ""
        src_part = f" ({item['source']}{rev_part})" if item.get("source") else ""
        target_str = " ".join(f"{k}:{v}" for k, v in item["targets"].items())
        print(f"{item['name']}  [{origin_tag}]{src_part}")
        print(f"  harnesses: {target_str}")
        desc = item["description"]
        if len(desc) > 100:
            desc = desc[:97] + "..."
        print(f"  {desc}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    state_dir = get_state_dir()
    active = collect_active_skills(state_dir)
    skill = active.get(args.name)
    if skill is None:
        raise SkillError(f"Unknown skill '{args.name}'")

    managed = load_managed(state_dir)
    targets = get_targets()
    target_info = {}
    for target in targets:
        managed_target = managed["targets"].get(str(target.path), {})
        target_info[target.label] = {
            "path": str(target.path / skill.name),
            "status": inspect_target_status(target, skill, managed_target),
        }

    payload = {
        "name": skill.name,
        "origin": skill.origin,
        "overridesDeclarative": skill.overrides_declarative,
        "sourceDir": str(skill.source_dir),
        "skillMd": str(skill.metadata.skill_md_path),
        "description": skill.metadata.description,
        "digest": skill.digest,
        "record": skill.record,
        "targets": target_info,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Name:        {skill.name}")
    origin = skill.origin
    if skill.overrides_declarative:
        origin += " (overrides declarative)"
    print(f"Origin:      {origin}")
    print(f"Source dir:  {skill.source_dir}")
    if skill.record.get("source"):
        print(f"Source:      {skill.record['source']}")
    if skill.record.get("rev"):
        print(f"Revision:    {skill.record['rev']}")
    print(f"Digest:      {skill.digest[:12]}")
    print(f"Description: {skill.metadata.description}")
    print("Harnesses:")
    for label, info in target_info.items():
        print(f"  - {label}: {info['status']} ({info['path']})")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    state_dir = get_state_dir()
    summary = sync_all(state_dir, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        prefix = "[dry-run] " if args.dry_run else ""
        for label, info in summary["targets"].items():
            changes = []
            if info["created"]:
                changes.append(f"+{len(info['created'])} ({', '.join(info['created'])})")
            if info["updated"]:
                changes.append(f"~{len(info['updated'])} ({', '.join(info['updated'])})")
            if info["removed"]:
                changes.append(f"-{len(info['removed'])} ({', '.join(info['removed'])})")
            if info["conflicts"]:
                changes.append(f"!conflict ({', '.join(info['conflicts'])})")
            status = ", ".join(changes) if changes else f"up to date ({len(info['unchanged'])} skills)"
            print(f"{prefix}{label}: {status}")
    return 1 if summary["conflicts"] else 0


def cmd_add(args: argparse.Namespace) -> int:
    state_dir = get_state_dir()
    installed_root = state_dir / "installed"
    manifest = load_manifest(state_dir)
    declarative = collect_declarative_skills()

    parsed = parse_source(args.source, ref_override=args.ref)
    if parsed.subpath and args.skill:
        raise SkillError("Do not combine a subpath in <source> with --skill")

    rev: str | None = None
    resolved_ref: str | None = parsed.ref

    with tempfile.TemporaryDirectory(prefix="homelab-skills-add-") as tmp:
        if parsed.kind == "local":
            assert parsed.local_path is not None
            search_root = parsed.local_path
        else:
            assert parsed.url is not None
            clone_dir = Path(tmp) / "repo"
            rev, resolved_ref = clone_git_repo(parsed.url, clone_dir, parsed.ref)
            search_root = clone_dir

        selected = select_skills_from_root(
            search_root,
            subpath=parsed.subpath,
            skill_selector=args.skill,
            install_all=args.all,
        )

        # Check collisions up front before mutating anything
        for _, _, meta in selected:
            dest = installed_root / meta.name
            if dest.exists() and not args.force:
                raise SkillError(
                    f"Skill '{meta.name}' is already installed. Use --force to overwrite or `skills update {meta.name}`."
                )

        installed_root.mkdir(parents=True, exist_ok=True)
        now = now_utc_iso()
        added_names: list[str] = []

        for skill_src, rel_subpath, meta in selected:
            dest = installed_root / meta.name
            replace_dir_atomically(skill_src, dest)
            if parsed.kind == "local":
                record: dict[str, Any] = {
                    "kind": "local",
                    "source": str(skill_src),
                    "installedAt": now,
                    "updatedAt": now,
                }
            else:
                if parsed.owner and parsed.repo:
                    canonical_src = (
                        f"github:{parsed.owner}/{parsed.repo}/{rel_subpath}"
                        if rel_subpath
                        else f"github:{parsed.owner}/{parsed.repo}"
                    )
                else:
                    canonical_src = parsed.url
                record = {
                    "kind": "git",
                    "source": canonical_src,
                    "url": parsed.url,
                    "owner": parsed.owner,
                    "repo": parsed.repo,
                    "subpath": rel_subpath,
                    "ref": resolved_ref,
                    "rev": rev,
                    "installedAt": now,
                    "updatedAt": now,
                }
            manifest["skills"][meta.name] = record
            added_names.append(meta.name)

        save_manifest(state_dir, manifest)

    summary = sync_all(state_dir)
    for name in added_names:
        extra = " (overrides declarative skill)" if name in declarative else ""
        rev_note = f" @ {rev[:10]}" if rev else ""
        print(f"Installed '{name}'{rev_note}{extra}")
    if summary["conflicts"]:
        for c in summary["conflicts"]:
            print(
                f"warning: unmanaged directory blocked sync at {c['path']}",
                file=sys.stderr,
            )
        return 1
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    state_dir = get_state_dir()
    manifest = load_manifest(state_dir)
    declarative = collect_declarative_skills()
    installed_root = state_dir / "installed"
    records: dict[str, Any] = manifest.get("skills", {})

    if args.name:
        if args.name not in records:
            if args.name in declarative:
                raise SkillError(
                    f"'{args.name}' is declarative; update its rev/hash in Homelab/components/skills/declarative.nix and run `just deploy`."
                )
            raise SkillError(f"Skill '{args.name}' is not in the installed manifest")
        names = [args.name]
    else:
        names = sorted(name for name, rec in records.items() if rec.get("kind") == "git")
        if not names:
            print("No git-installed skills to update.")
            return 0

    changed_any = False
    for name in names:
        rec = records[name]
        if rec.get("kind") != "git":
            print(f"Skipping '{name}' (installed from local path, not git)")
            continue
        url = rec.get("url")
        if not url:
            raise SkillError(f"Installed skill '{name}' is missing git URL in manifest")
        old_rev = rec.get("rev")
        subpath = rec.get("subpath")
        ref = args.ref or rec.get("ref")

        with tempfile.TemporaryDirectory(prefix="homelab-skills-upd-") as tmp:
            clone_dir = Path(tmp) / "repo"
            new_rev, resolved_ref = clone_git_repo(url, clone_dir, ref)
            selected = select_skills_from_root(
                clone_dir,
                subpath=subpath,
                skill_selector=None if subpath else name,
                install_all=False,
            )
            skill_src, _, meta = selected[0]
            if meta.name != name:
                raise SkillError(
                    f"Upstream skill renamed from '{name}' to '{meta.name}'; reinstall manually."
                )
            if new_rev == old_rev and not args.force:
                print(f"{name}: already up to date ({new_rev[:10]})")
                continue
            replace_dir_atomically(skill_src, installed_root / name)
            rec["rev"] = new_rev
            rec["ref"] = resolved_ref
            rec["updatedAt"] = now_utc_iso()
            changed_any = True
            old_short = old_rev[:10] if isinstance(old_rev, str) else "unknown"
            print(f"{name}: updated {old_short} -> {new_rev[:10]}")

    if changed_any:
        save_manifest(state_dir, manifest)
    summary = sync_all(state_dir)
    return 1 if summary["conflicts"] else 0


def cmd_remove(args: argparse.Namespace) -> int:
    state_dir = get_state_dir()
    installed_root = state_dir / "installed"
    manifest = load_manifest(state_dir)
    declarative = collect_declarative_skills()

    target_dir = installed_root / args.name
    in_manifest = args.name in manifest.get("skills", {})
    if not target_dir.exists() and not in_manifest:
        if args.name in declarative:
            raise SkillError(
                f"'{args.name}' is a declarative skill; remove it from Homelab/components/skills/declarative.nix and run `just deploy`."
            )
        raise SkillError(f"Skill '{args.name}' is not installed")

    if target_dir.is_symlink() or target_dir.is_file():
        target_dir.unlink()
    elif target_dir.is_dir():
        shutil.rmtree(target_dir)
    manifest["skills"].pop(args.name, None)
    save_manifest(state_dir, manifest)

    summary = sync_all(state_dir)
    if args.name in declarative:
        print(f"Removed mutable override for '{args.name}'; restored declarative version.")
    else:
        print(f"Removed '{args.name}' and pruned harness copies.")
    return 1 if summary["conflicts"] else 0


def prefetch_github_sri_hash(owner: str, repo: str, rev: str) -> str | None:
    if not shutil.which("nix-prefetch-url") or not shutil.which("nix"):
        return None
    url = f"https://github.com/{owner}/{repo}/archive/{rev}.tar.gz"
    pref = subprocess.run(
        ["nix-prefetch-url", "--unpack", url],
        capture_output=True,
        text=True,
        check=False,
    )
    if pref.returncode != 0:
        return None
    nix32 = pref.stdout.strip().splitlines()[-1].strip()
    conv = subprocess.run(
        ["nix", "hash", "convert", "--hash-algo", "sha256", "--to", "sri", nix32],
        capture_output=True,
        text=True,
        check=False,
    )
    if conv.returncode != 0:
        return None
    return conv.stdout.strip()


def cmd_export_nix(args: argparse.Namespace) -> int:
    state_dir = get_state_dir()
    active = collect_active_skills(state_dir)
    skill = active.get(args.name)
    if skill is None:
        raise SkillError(f"Unknown skill '{args.name}'")

    rec = skill.record
    if rec.get("owner") and rec.get("repo") and rec.get("rev"):
        owner = rec["owner"]
        repo = rec["repo"]
        rev = rec["rev"]
        subpath = rec.get("subpath")
        var_name = re.sub(r"[^A-Za-z0-9_]", "_", f"{owner}_{repo}")
        sri_hash = None if args.no_prefetch else prefetch_github_sri_hash(owner, repo, rev)
        hash_expr = f'"{sri_hash}"' if sri_hash else "lib.fakeHash"
        skill_path = f'"${{{var_name}}}/{subpath}"' if subpath else var_name
        canonical_source = (
            f"github:{owner}/{repo}/{subpath}" if subpath else f"github:{owner}/{repo}"
        )
        print("# Add to /home/rishabh/Projects/Homelab/components/skills/declarative.nix:")
        print(f"  {var_name} = pkgs.fetchFromGitHub {{")
        print(f'    owner = "{owner}";')
        print(f'    repo = "{repo}";')
        print(f'    rev = "{rev}";')
        print(f"    hash = {hash_expr};")
        print("  };")
        print()
        print(f'  "{skill.name}" = {{')
        print(f"    path = {skill_path};")
        print(f'    source = "{canonical_source}";')
        print(f'    rev = "{rev}";')
        print("  };")
        if skill.origin == "installed":
            print()
            print(f"# After `just deploy`, run: skills remove {skill.name}")
        return 0

    print("# Local skill: copy into Homelab and declare in components/skills/declarative.nix:")
    print(
        f"#   cp -r {skill.source_dir} /home/rishabh/Projects/Homelab/components/skills/builtin/{skill.name}"
    )
    print(f'  "{skill.name}" = {{')
    print(f"    path = ./builtin/{skill.name};")
    print(f'    source = "homelab:builtin/{skill.name}";')
    print("  };")
    if skill.origin == "installed":
        print(f"# After `just deploy`, run: skills remove {skill.name}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    state_dir = get_state_dir()
    active = collect_active_skills(state_dir)
    managed = load_managed(state_dir)
    targets = get_targets()

    errors: list[str] = []
    warnings: list[str] = []

    print(f"State dir:       {state_dir}")
    print(f"Declarative dir: {get_declarative_dir() or '(none)'}")
    print(f"Active skills:   {len(active)}")

    for name, skill in active.items():
        if skill.overrides_declarative:
            warnings.append(
                f"Skill '{name}' in installed/ overrides declarative version (run `skills remove {name}` to use declarative)"
            )
        for target in targets:
            managed_target = managed["targets"].get(str(target.path), {})
            status = inspect_target_status(target, skill, managed_target)
            if status != "ok":
                errors.append(f"{target.label}/{name}: {status} ({target.path / name})")

    for target in targets:
        if not target.path.is_dir():
            errors.append(f"Target directory missing: {target.label} ({target.path})")
        else:
            print(f"Target {target.label:12s} {target.path} (ok)")

    # Warn about duplicates in ~/.agents/skills (which Codex also scans)
    for extra_dir in get_extra_scan_dirs():
        if extra_dir.is_dir():
            for entry in sorted(extra_dir.iterdir(), key=lambda p: p.name):
                if entry.name in active:
                    warnings.append(
                        f"Duplicate skill '{entry.name}' also exists in {extra_dir} (Codex may list it twice)"
                    )

    # Check T3 Antigravity isolated profile symlinks (informational)
    t3_agy_root = get_t3_antigravity_root()
    if t3_agy_root.is_dir():
        profiles = [p for p in sorted(t3_agy_root.iterdir()) if p.is_dir()]
        for prof in profiles:
            link = prof / "config" / "skills"
            if link.is_symlink():
                print(f"T3 Antigravity link: {link} -> {os.readlink(link)}")
            else:
                warnings.append(
                    f"T3 Antigravity profile {prof.name[:12]}... has not linked config/skills yet (starts automatically on next Antigravity session)"
                )

    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}", file=sys.stderr)

    if errors:
        return 1
    print("Doctor check passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skills",
        description="Manage global cross-harness agent skills (Codex, Claude Code, Antigravity).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", aliases=["ls"], help="List active skills and harness sync status")
    p_list.add_argument("--json", action="store_true", help="Output JSON")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show details for one skill")
    p_show.add_argument("name", help="Skill name")
    p_show.add_argument("--json", action="store_true", help="Output JSON")
    p_show.set_defaults(func=cmd_show)

    p_add = sub.add_parser("add", aliases=["install"], help="Install a skill into the mutable store and sync")
    p_add.add_argument("source", help="Local path, github:owner/repo[/subpath], GitHub URL, or git URL")
    p_add.add_argument("--skill", help="Skill name or subpath inside a multi-skill repository")
    p_add.add_argument("--all", action="store_true", help="Install all skills in a multi-skill repository")
    p_add.add_argument("--ref", help="Git branch, tag, or commit SHA")
    p_add.add_argument("--force", action="store_true", help="Overwrite an existing installed skill")
    p_add.set_defaults(func=cmd_add)

    p_upd = sub.add_parser("update", help="Update git-installed skill(s)")
    p_upd.add_argument("name", nargs="?", help="Skill name (omit to update all git-installed skills)")
    p_upd.add_argument("--ref", help="Override git branch, tag, or commit SHA")
    p_upd.add_argument("--force", action="store_true", help="Re-copy even if commit SHA is unchanged")
    p_upd.set_defaults(func=cmd_update)

    p_rm = sub.add_parser("remove", aliases=["rm", "uninstall"], help="Remove a mutable installed skill")
    p_rm.add_argument("name", help="Skill name")
    p_rm.set_defaults(func=cmd_remove)

    p_sync = sub.add_parser("sync", help="Reconcile active skills across all harness directories")
    p_sync.add_argument("--dry-run", action="store_true", help="Report planned changes without modifying files")
    p_sync.add_argument("--json", action="store_true", help="Output JSON summary")
    p_sync.set_defaults(func=cmd_sync)

    p_nix = sub.add_parser(
        "export-nix",
        aliases=["promote"],
        help="Print a declarative.nix snippet to promote an installed skill into Homelab",
    )
    p_nix.add_argument("name", help="Skill name")
    p_nix.add_argument("--no-prefetch", action="store_true", help="Emit lib.fakeHash instead of running nix-prefetch-url")
    p_nix.set_defaults(func=cmd_export_nix)

    p_doc = sub.add_parser("doctor", help="Verify skill integrity and harness synchronization")
    p_doc.set_defaults(func=cmd_doctor)

    p_val = sub.add_parser("validate", help="Validate a single skill directory")
    p_val.add_argument("path", help="Path to skill directory")
    p_val.add_argument("--expected-name", help="Assert that SKILL.md frontmatter name matches this value")
    p_val.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SkillError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
