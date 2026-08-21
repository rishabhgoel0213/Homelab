#!/usr/bin/env python3
"""Manage and publish the private Quarto blog."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml
from aiohttp import web


SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MUTATION_HEADER = "X-Blog-Admin"
MAX_LOG_CHARS = 40_000
PROJECT_IMPORTS_FILE = ".blog-projects.json"
PROJECT_LINKS_DIRECTORY = ".blog-projects"
PROJECT_IMPORT_SCHEMA = 1
PROJECT_POST_PREFIX = "project:"
PROJECT_COPY_IGNORES = {
    ".direnv",
    ".git",
    ".ipynb_checkpoints",
    ".quarto",
    "__pycache__",
    "node_modules",
    "result",
    "_site",
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80].rstrip("-")


def validate_slug(slug: str) -> str:
    if not SLUG_RE.fullmatch(slug) or len(slug) > 80:
        raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens.")
    return slug


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def normalize_metadata(data: dict[str, Any]) -> dict[str, Any]:
    title = str(data.get("title", "")).strip()
    if not title:
        raise ValueError("Title is required.")

    raw_categories = data.get("categories", [])
    if isinstance(raw_categories, str):
        raw_categories = raw_categories.split(",")
    if not isinstance(raw_categories, list):
        raise ValueError("Categories must be a list.")
    categories = [str(item).strip() for item in raw_categories if str(item).strip()]

    post_date = str(data.get("date", date.today().isoformat())).strip()
    try:
        date.fromisoformat(post_date)
    except ValueError as exc:
        raise ValueError("Date must use YYYY-MM-DD format.") from exc

    metadata: dict[str, Any] = {
        "title": title,
        "date": post_date,
        "draft": bool(data.get("draft", True)),
    }
    description = str(data.get("description", "")).strip()
    if description:
        metadata["description"] = description
    if categories:
        metadata["categories"] = categories
    return metadata


def metadata_text(metadata: dict[str, Any]) -> str:
    return yaml.safe_dump(metadata, sort_keys=False, allow_unicode=False)


def prune_draft_outputs(source: Path, output: Path) -> None:
    posts_source = source / "posts"
    posts_output = (output / "posts").resolve()
    if not posts_source.is_dir():
        return

    for metadata_path in posts_source.rglob("_metadata.yml"):
        post_dir = metadata_path.parent
        relative = post_dir.relative_to(posts_source)
        if "_project" in relative.parts:
            continue
        metadata = (
            yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
            if metadata_path.is_file()
            else {}
        )
        if isinstance(metadata, dict) and bool(metadata.get("draft", False)):
            rendered = (posts_output / relative).resolve()
            try:
                rendered.relative_to(posts_output)
            except ValueError:
                continue
            shutil.rmtree(rendered, ignore_errors=True)


def install_resume(resume: Path | None, output: Path) -> None:
    if resume is None:
        return
    if not resume.is_file():
        raise RuntimeError(f"Resume does not exist: {resume}")
    shutil.copy2(resume, output / "rishabh-goel-resume.pdf")


def ignored_project_entry(_directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in PROJECT_COPY_IGNORES or name.endswith(".pyc")
    }


def discover_notebooks(root: Path) -> list[Path]:
    notebooks: list[Path] = []
    for path in root.rglob("*.ipynb"):
        relative = path.relative_to(root)
        if any(part.startswith(".") or part in PROJECT_COPY_IGNORES for part in relative.parts):
            continue
        if path.is_file():
            notebooks.append(path)
    return sorted(notebooks, key=lambda path: path.relative_to(root).as_posix().casefold())


def notebook_metadata(path: Path, default_date: str) -> dict[str, Any]:
    title = path.stem.replace("-", " ").replace("_", " ").strip().title() or "Notebook"
    post_date = default_date
    try:
        notebook = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        notebook = {}

    metadata = notebook.get("metadata", {}) if isinstance(notebook, dict) else {}
    has_metadata_title = False
    if isinstance(metadata, dict):
        raw_title = metadata.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            title = raw_title.strip()
            has_metadata_title = True
        raw_date = str(metadata.get("date", "")).strip()
        try:
            date.fromisoformat(raw_date)
        except ValueError:
            pass
        else:
            post_date = raw_date

    cells = notebook.get("cells", []) if isinstance(notebook, dict) else []
    if not has_metadata_title:
        for cell in cells if isinstance(cells, list) else []:
            if not isinstance(cell, dict) or cell.get("cell_type") != "markdown":
                continue
            source = cell.get("source", [])
            text = "".join(source) if isinstance(source, list) else str(source)
            heading = re.search(r"^\s*#{1,6}\s+(.+?)\s*$", text, re.MULTILINE)
            if heading:
                title = heading.group(1).strip().rstrip("#").strip()
                break

    return {"title": title, "date": post_date, "draft": True}


def project_post_id(project_id: str, relative: str) -> str:
    token = base64.urlsafe_b64encode(relative.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{PROJECT_POST_PREFIX}{project_id}:{token}"


class ProjectCatalog:
    def __init__(self, executable: str) -> None:
        self.executable = executable

    def list_projects(self) -> list[dict[str, Any]]:
        result = subprocess.run(
            [self.executable, "list", "--json"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise RuntimeError(f"Could not list projects: {detail}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("projectctl returned invalid JSON.") from exc
        projects = payload.get("projects", []) if isinstance(payload, dict) else []
        if not isinstance(projects, list):
            raise RuntimeError("projectctl returned an invalid project list.")
        return [project for project in projects if isinstance(project, dict)]


class BlogStore:
    def __init__(
        self,
        source: Path,
        editor_url: str = "",
        public_url: str = "",
        preview_url: str = "",
        projectctl: str = "/run/current-system/sw/bin/projectctl",
    ) -> None:
        self.source = source.resolve()
        self.posts = self.source / "posts"
        self.project_links = self.source / PROJECT_LINKS_DIRECTORY
        self.project_imports = self.source / PROJECT_IMPORTS_FILE
        self.editor_url = editor_url.rstrip("/")
        self.public_url = public_url.rstrip("/")
        self.preview_url = preview_url.rstrip("/")
        self.catalog = ProjectCatalog(projectctl)

    def ensure(self) -> None:
        if not (self.source / "_quarto.yml").is_file():
            raise RuntimeError(f"Not a Quarto blog project: {self.source}")
        self.posts.mkdir(parents=True, exist_ok=True)

    def post_dir(self, slug: str) -> Path:
        validate_slug(slug)
        path = (self.posts / slug).resolve()
        if path.parent != self.posts.resolve():
            raise ValueError("Invalid post path.")
        return path

    def _read_project_imports(self) -> dict[str, Any]:
        if not self.project_imports.is_file():
            return {"schema": PROJECT_IMPORT_SCHEMA, "projects": []}
        try:
            data = json.loads(self.project_imports.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid project import registry: {self.project_imports}") from exc
        if not isinstance(data, dict) or data.get("schema") != PROJECT_IMPORT_SCHEMA:
            raise ValueError(f"Unsupported project import registry: {self.project_imports}")
        projects = data.get("projects", [])
        if not isinstance(projects, list) or not all(isinstance(item, dict) for item in projects):
            raise ValueError(f"Invalid project import registry: {self.project_imports}")
        return data

    def _write_project_imports(self, data: dict[str, Any]) -> None:
        atomic_write(self.project_imports, json.dumps(data, indent=2, sort_keys=True) + "\n")

    def _project_root(self, project: dict[str, Any]) -> Path:
        slug = validate_slug(str(project.get("slug", "")))
        link = self.project_links / slug
        if not link.is_symlink():
            raise RuntimeError(f"Imported project link is missing: {link}")
        try:
            root = link.resolve(strict=True)
        except FileNotFoundError as exc:
            raise RuntimeError(f"Imported project is no longer available: {link}") from exc
        if not root.is_dir():
            raise RuntimeError(f"Imported project is not a directory: {root}")
        return root

    @staticmethod
    def _project_notebook_metadata(
        project: dict[str, Any], notebook: Path, root: Path
    ) -> dict[str, Any]:
        imported_at = str(project.get("importedAt", date.today().isoformat()))
        metadata = notebook_metadata(notebook, imported_at)
        relative = notebook.relative_to(root).as_posix()
        overrides = project.get("notebooks", {}).get(relative, {})
        if isinstance(overrides, dict):
            metadata.update(overrides)
        return normalize_metadata(metadata)

    def _describe_project_notebook(
        self, project: dict[str, Any], notebook: Path, root: Path
    ) -> dict[str, Any]:
        relative = notebook.relative_to(root).as_posix()
        metadata = self._project_notebook_metadata(project, notebook, root)
        project_slug = validate_slug(str(project.get("slug", "")))
        rendered = Path("posts") / project_slug / Path(relative).with_suffix("")
        rendered_url = f"/{rendered.as_posix()}/"
        post_base_url = self.preview_url if metadata["draft"] and self.preview_url else self.public_url
        editor_path = quote(str(notebook), safe="/")
        return {
            "id": project_post_id(str(project.get("id", "")), relative),
            "slug": f"{project_slug}/{Path(relative).with_suffix('').as_posix()}",
            "title": metadata["title"],
            "date": metadata["date"],
            "description": metadata.get("description", ""),
            "categories": metadata.get("categories", []),
            "draft": metadata["draft"],
            "kind": "project notebook",
            "origin": "project",
            "projectId": str(project.get("id", "")),
            "projectName": str(project.get("name", project_slug)),
            "projectTitle": str(project.get("title", project_slug)),
            "source": f"{project.get('name', project_slug)}/{relative}",
            "editorUrl": f"{self.editor_url}/lab/tree{editor_path}" if self.editor_url else "",
            "postUrl": f"{post_base_url}{quote(rendered_url, safe='/')}"
            if post_base_url
            else quote(rendered_url, safe="/"),
        }

    def _project_posts(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for project in self._read_project_imports()["projects"]:
            root = self._project_root(project)
            result.extend(
                self._describe_project_notebook(project, notebook, root)
                for notebook in discover_notebooks(root)
            )
        return result

    def list_projects(self) -> list[dict[str, Any]]:
        imported = {
            str(project.get("id")): project for project in self._read_project_imports()["projects"]
        }
        result: list[dict[str, Any]] = []
        for project in self.catalog.list_projects():
            root_value = project.get("root")
            if not isinstance(root_value, str):
                continue
            root = Path(root_value).resolve()
            if root == self.source or not root.is_dir():
                continue
            notebooks = discover_notebooks(root)
            project_id = str(project.get("id", ""))
            result.append(
                {
                    "id": project_id,
                    "name": str(project.get("name", root.name)),
                    "title": str(project.get("title", root.name)),
                    "root": str(root),
                    "managed": bool(project.get("managed", False)),
                    "environment": str(project.get("environment", "host")),
                    "notebookCount": len(notebooks),
                    "imported": project_id in imported,
                }
            )
        return sorted(result, key=lambda project: project["title"].casefold())

    def import_project(self, reference: str) -> dict[str, Any]:
        projects = self.catalog.list_projects()
        matches = [
            project
            for project in projects
            if reference in {str(project.get("id", "")), str(project.get("name", ""))}
        ]
        if len(matches) != 1:
            raise FileNotFoundError(f"Project '{reference}' does not exist.")
        selected = matches[0]
        root_value = selected.get("root")
        if not isinstance(root_value, str):
            raise ValueError("Project has no valid root path.")
        root = Path(root_value).resolve()
        if root == self.source:
            raise ValueError("The blog project cannot import itself.")
        if not root.is_dir():
            raise FileNotFoundError(f"Project directory does not exist: {root}")
        notebooks = discover_notebooks(root)
        if not notebooks:
            raise ValueError("The selected project does not contain any Jupyter notebooks.")

        data = self._read_project_imports()
        project_id = str(selected.get("id", ""))
        if any(str(project.get("id", "")) == project_id for project in data["projects"]):
            raise FileExistsError(f"Project '{selected.get('name', root.name)}' is already imported.")
        slug = validate_slug(slugify(str(selected.get("name", root.name))))
        if self.post_dir(slug).exists() or any(
            str(project.get("slug", "")) == slug for project in data["projects"]
        ):
            raise FileExistsError(f"A blog post or project already uses the slug '{slug}'.")

        self.project_links.mkdir(parents=True, exist_ok=True)
        link = self.project_links / slug
        if link.exists() or link.is_symlink():
            raise FileExistsError(f"A project link already exists: {link}")
        link.symlink_to(root, target_is_directory=True)
        record = {
            "id": project_id,
            "name": str(selected.get("name", root.name)),
            "title": str(selected.get("title", root.name)),
            "slug": slug,
            "importedAt": date.today().isoformat(),
            "notebooks": {},
        }
        data["projects"].append(record)
        try:
            self._write_project_imports(data)
        except Exception:
            link.unlink(missing_ok=True)
            raise
        posts = [self._describe_project_notebook(record, notebook, root) for notebook in notebooks]
        return {"project": record, "posts": posts}

    def read_metadata(self, post_dir: Path) -> dict[str, Any]:
        path = post_dir / "_metadata.yml"
        if not path.is_file():
            return {"title": post_dir.name, "date": date.today().isoformat(), "draft": True}
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Invalid metadata in {path}")
        return loaded

    def describe(self, post_dir: Path) -> dict[str, Any]:
        metadata = self.read_metadata(post_dir)
        raw_categories = metadata.get("categories", [])
        if isinstance(raw_categories, str):
            categories = [raw_categories]
        elif isinstance(raw_categories, list):
            categories = [str(item) for item in raw_categories]
        else:
            categories = []
        notebook = post_dir / "index.ipynb"
        document = notebook if notebook.is_file() else post_dir / "index.qmd"
        kind = "notebook" if notebook.is_file() else "document"
        relative_source = document.relative_to(self.source).as_posix()
        editor_path = quote(str(document), safe="/")
        draft = bool(metadata.get("draft", False))
        post_base_url = self.preview_url if draft and self.preview_url else self.public_url
        return {
            "id": post_dir.name,
            "slug": post_dir.name,
            "title": str(metadata.get("title", post_dir.name)),
            "date": str(metadata.get("date", "")),
            "description": str(metadata.get("description", "")),
            "categories": categories,
            "draft": draft,
            "kind": kind,
            "origin": "upload",
            "source": relative_source,
            "editorUrl": f"{self.editor_url}/lab/tree{editor_path}" if self.editor_url else "",
            "postUrl": f"{post_base_url}/posts/{post_dir.name}/"
            if post_base_url
            else f"/posts/{post_dir.name}/",
        }

    def list_posts(self) -> list[dict[str, Any]]:
        self.ensure()
        result = [
            self.describe(path)
            for path in self.posts.iterdir()
            if path.is_dir() and not path.is_symlink()
        ]
        result.extend(self._project_posts())
        return sorted(result, key=lambda post: (post["date"], post["slug"]), reverse=True)

    def get(self, post_id: str) -> dict[str, Any]:
        if post_id.startswith(PROJECT_POST_PREFIX):
            project, notebook, root, _registry = self._find_project_post(post_id)
            return self._describe_project_notebook(project, notebook, root)

        post_dir = self.post_dir(post_id)
        if not post_dir.is_dir() or post_dir.is_symlink():
            raise FileNotFoundError(f"Post '{post_id}' does not exist.")
        return self.describe(post_dir)

    def create(self, data: dict[str, Any], notebook: bytes | None = None) -> dict[str, Any]:
        self.ensure()
        metadata = normalize_metadata(data)
        slug = validate_slug(str(data.get("slug") or slugify(metadata["title"])))
        post_dir = self.post_dir(slug)
        imported_slugs = {
            str(project.get("slug", "")) for project in self._read_project_imports()["projects"]
        }
        if post_dir.exists() or slug in imported_slugs:
            raise FileExistsError(f"A post named '{slug}' already exists.")

        post_dir.mkdir()
        try:
            atomic_write(post_dir / "_metadata.yml", metadata_text(metadata))
            if notebook is None:
                atomic_write(post_dir / "index.qmd", "<!-- Write the post here. -->\n")
            else:
                parsed = json.loads(notebook)
                if not isinstance(parsed, dict) or not isinstance(parsed.get("cells"), list):
                    raise ValueError("The uploaded file is not a valid Jupyter notebook.")
                atomic_write(post_dir / "index.ipynb", json.dumps(parsed, indent=1) + "\n")
        except Exception:
            shutil.rmtree(post_dir)
            raise
        return self.describe(post_dir)

    def _find_project_post(
        self, post_id: str
    ) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
        data = self._read_project_imports()
        for project in data["projects"]:
            root = self._project_root(project)
            for notebook in discover_notebooks(root):
                relative = notebook.relative_to(root).as_posix()
                if project_post_id(str(project.get("id", "")), relative) == post_id:
                    return project, notebook, root, data
        raise FileNotFoundError("Project notebook does not exist.")

    def update(self, post_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if post_id.startswith(PROJECT_POST_PREFIX):
            project, notebook, root, registry = self._find_project_post(post_id)
            metadata = normalize_metadata(data)
            relative = notebook.relative_to(root).as_posix()
            overrides = project.setdefault("notebooks", {})
            if not isinstance(overrides, dict):
                raise ValueError("Invalid project notebook metadata registry.")
            overrides[relative] = metadata
            self._write_project_imports(registry)
            return self._describe_project_notebook(project, notebook, root)

        post_dir = self.post_dir(post_id)
        if not post_dir.is_dir():
            raise FileNotFoundError(f"Post '{post_id}' does not exist.")
        metadata = normalize_metadata(data)
        atomic_write(post_dir / "_metadata.yml", metadata_text(metadata))
        return self.describe(post_dir)

    def set_draft(self, post_id: str, draft: bool) -> dict[str, Any]:
        metadata = self.get(post_id)
        metadata["draft"] = draft
        return self.update(post_id, metadata)

    def delete(self, post_id: str) -> dict[str, Any]:
        if post_id.startswith(PROJECT_POST_PREFIX):
            project, _notebook, root, registry = self._find_project_post(post_id)
            project_id = str(project.get("id", ""))
            notebooks = discover_notebooks(root)
            slug = validate_slug(str(project.get("slug", "")))
            link = self.project_links / slug
            if not link.is_symlink():
                raise RuntimeError(f"Imported project link is missing: {link}")
            link.unlink()
            registry["projects"] = [
                item for item in registry["projects"] if str(item.get("id", "")) != project_id
            ]
            try:
                self._write_project_imports(registry)
            except Exception:
                link.symlink_to(root, target_is_directory=True)
                raise
            return {
                "removed": "project",
                "title": str(project.get("title", slug)),
                "count": len(notebooks),
            }

        post_dir = self.post_dir(post_id)
        if not post_dir.is_dir() or post_dir.is_symlink():
            raise FileNotFoundError(f"Post '{post_id}' does not exist.")
        post = self.describe(post_dir)
        shutil.rmtree(post_dir)
        return {"removed": "post", "title": post["title"], "count": 1}

    def prepare_build_source(self, destination: Path) -> None:
        for project in self._read_project_imports()["projects"]:
            root = self._project_root(project)
            slug = validate_slug(str(project.get("slug", "")))
            target = destination / "posts" / slug
            assets = target / "_project"
            if target.exists() or target.is_symlink():
                raise RuntimeError(f"Project import conflicts with build path: {target}")
            shutil.copytree(
                root,
                assets,
                symlinks=True,
                ignore=ignored_project_entry,
            )
            for notebook in discover_notebooks(root):
                relative = notebook.relative_to(root)
                post_dir = target / relative.with_suffix("")
                post_dir.mkdir(parents=True)
                staged_notebook = post_dir / "index.ipynb"
                shutil.copy2(notebook, staged_notebook, follow_symlinks=True)
                notebook_assets = assets / relative.parent
                for entry in notebook_assets.iterdir():
                    if entry.suffix == ".ipynb" or entry.name in {"index.ipynb", "_metadata.yml"}:
                        continue
                    linked = post_dir / entry.name
                    if linked.exists() or linked.is_symlink():
                        continue
                    linked.symlink_to(entry, target_is_directory=entry.is_dir())
                project_link = post_dir / "_project"
                if not project_link.exists() and not project_link.is_symlink():
                    project_link.symlink_to(assets, target_is_directory=True)
                try:
                    content = json.loads(staged_notebook.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ValueError(f"Invalid Jupyter notebook: {notebook}") from exc
                if not isinstance(content, dict) or not isinstance(content.get("cells"), list):
                    raise ValueError(f"Invalid Jupyter notebook: {notebook}")
                existing_metadata = content.get("metadata", {})
                if not isinstance(existing_metadata, dict):
                    existing_metadata = {}
                post_metadata = self._project_notebook_metadata(project, notebook, root)
                existing_metadata.update(post_metadata)
                resource_parent = Path("_project") / relative.parent
                existing_metadata["resource-path"] = [resource_parent.as_posix(), "_project"]
                content["metadata"] = existing_metadata
                atomic_write(staged_notebook, json.dumps(content, indent=1) + "\n")
                atomic_write(post_dir / "_metadata.yml", metadata_text(post_metadata))

        config_path = destination / "_quarto.yml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(config, dict):
            raise ValueError(f"Invalid Quarto configuration: {config_path}")
        project_config = config.setdefault("project", {})
        if not isinstance(project_config, dict):
            raise ValueError(f"Invalid Quarto project configuration: {config_path}")
        project_config["render"] = [
            "index.qmd",
            "about.qmd",
            "posts/**/*.qmd",
            "posts/**/*.ipynb",
            "!posts/**/.ipynb_checkpoints/**",
            "!posts/**/_project/**",
        ]
        atomic_write(config_path, yaml.safe_dump(config, sort_keys=False, allow_unicode=False))


class Publisher:
    def __init__(
        self,
        source: Path,
        state: Path,
        quarto: str,
        rsync: str,
        resume: Path | None = None,
        preview_state: Path | None = None,
        store: BlogStore | None = None,
    ) -> None:
        self.source = source.resolve()
        self.state = state.resolve()
        self.quarto = quarto
        self.rsync = rsync
        self.resume = resume.resolve() if resume else None
        self.preview_state = preview_state.resolve() if preview_state else None
        self.store = store
        self.lock = threading.Lock()
        self.status: dict[str, Any] = {"state": "idle", "log": "", "finishedAt": None}

    def _render(
        self,
        build_source: Path,
        arguments: list[str],
        failure_message: str,
        log: str = "",
    ) -> str:
        render = subprocess.run(
            [self.quarto, "render", str(build_source), "--no-execute", *arguments],
            cwd=build_source,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=900,
            check=False,
        )
        log = (log + ANSI_RE.sub("", render.stdout))[-MAX_LOG_CHARS:]
        if render.returncode != 0:
            self.status = {"state": "failed", "log": log, "finishedAt": None}
            raise RuntimeError(failure_message)
        if not (build_source / "_site" / "index.html").is_file():
            raise RuntimeError("Quarto completed without producing _site/index.html.")
        return log

    def _deploy(self, output: Path, destination: Path, failure_message: str, log: str) -> str:
        install_resume(self.resume, output)
        destination.mkdir(parents=True, exist_ok=True)
        deploy = subprocess.run(
            [self.rsync, "-a", "--delete", f"{output}/", f"{destination}/"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
            check=False,
        )
        log = (log + ANSI_RE.sub("", deploy.stdout))[-MAX_LOG_CHARS:]
        if deploy.returncode != 0:
            self.status = {"state": "failed", "log": log, "finishedAt": None}
            raise RuntimeError(failure_message)
        return log

    def _render_preview(self, build_source: Path, log: str = "") -> str:
        if not self.preview_state:
            raise RuntimeError("Internal preview output is not configured.")
        log = self._render(
            build_source,
            ["-M", "draft-mode:visible"],
            "Quarto preview render failed. Check the build log.",
            log,
        )
        return self._deploy(
            build_source / "_site",
            self.preview_state,
            "Rendered successfully, but preview deployment failed.",
            log,
        )

    def _copy_source(self, destination: Path) -> None:
        shutil.copytree(
            self.source,
            destination,
            symlinks=True,
            ignore=shutil.ignore_patterns(".git", ".quarto", "_site", "__pycache__", "*.pyc"),
        )
        if self.store:
            self.store.prepare_build_source(destination)

    def _begin(self, state: str) -> None:
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("A blog build is already running.")
        self.status = {"state": state, "log": "", "finishedAt": None}

    def _finish(self, state: str, log: str) -> dict[str, Any]:
        finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.status = {"state": state, "log": log, "finishedAt": finished}
        return self.status

    def preview(self) -> dict[str, Any]:
        self._begin("previewing")
        try:
            with tempfile.TemporaryDirectory(prefix="blog-preview-") as temporary:
                build_source = Path(temporary) / "source"
                self._copy_source(build_source)
                return self._finish("previewed", self._render_preview(build_source))
        finally:
            self.lock.release()

    def publish(self) -> dict[str, Any]:
        self._begin("building")
        try:
            with tempfile.TemporaryDirectory(prefix="blog-publish-") as temporary:
                build_source = Path(temporary) / "source"
                self._copy_source(build_source)
                log = ""
                output = build_source / "_site"

                if self.preview_state:
                    log = self._render_preview(build_source, log)
                    shutil.rmtree(output)

                log = self._render(build_source, [], "Quarto render failed. Check the build log.", log)
                prune_draft_outputs(build_source, output)
                log = self._deploy(
                    output,
                    self.state,
                    "Rendered successfully, but deployment failed.",
                    log,
                )
                return self._finish("published", log)
        finally:
            self.lock.release()


def set_publication(
    store: BlogStore,
    publisher: Publisher,
    post_id: str,
    *,
    draft: bool,
) -> dict[str, Any]:
    previous = store.get(post_id)
    post = store.set_draft(post_id, draft)
    try:
        build = publisher.publish()
    except Exception:
        if bool(previous["draft"]) != draft:
            store.set_draft(post_id, bool(previous["draft"]))
        raise
    return {"post": post, "build": build}


def require_mutation_header(request: web.Request) -> None:
    if request.headers.get(MUTATION_HEADER) != "1":
        raise web.HTTPForbidden(text="Missing admin request header.")


@web.middleware
async def error_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except FileNotFoundError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except FileExistsError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    except (ValueError, json.JSONDecodeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        return web.json_response({"error": str(exc)}, status=500)


def create_app(store: BlogStore, publisher: Publisher, assets: Path) -> web.Application:
    app = web.Application(middlewares=[error_middleware], client_max_size=64 * 1024**2)

    async def index(_request: web.Request) -> web.FileResponse:
        return web.FileResponse(assets / "index.html", headers={"Cache-Control": "no-store"})

    async def asset(request: web.Request) -> web.FileResponse:
        name = request.match_info["name"]
        if name not in {"app.js", "styles.css"}:
            raise web.HTTPNotFound()
        return web.FileResponse(assets / name, headers={"Cache-Control": "no-store"})

    async def posts(_request: web.Request) -> web.Response:
        return web.json_response({"posts": store.list_posts()})

    async def projects(_request: web.Request) -> web.Response:
        return web.json_response({"projects": store.list_projects()})

    async def create_post(request: web.Request) -> web.Response:
        require_mutation_header(request)
        return web.json_response(store.create(await request.json()), status=201)

    async def update_post(request: web.Request) -> web.Response:
        require_mutation_header(request)
        return web.json_response(store.update(request.match_info["slug"], await request.json()))

    async def delete_post(request: web.Request) -> web.Response:
        require_mutation_header(request)
        removed = store.delete(request.match_info["slug"])
        preview_status = await asyncio.to_thread(publisher.preview)
        return web.json_response({**removed, "preview": preview_status})

    async def import_notebook(request: web.Request) -> web.Response:
        require_mutation_header(request)
        reader = await request.multipart()
        values: dict[str, Any] = {"draft": True}
        notebook: bytes | None = None
        async for field in reader:
            if field.name == "notebook":
                notebook = await field.read(decode=False)
            elif field.name:
                values[field.name] = await field.text()
        if notebook is None:
            raise ValueError("Choose a Jupyter notebook to import.")
        return web.json_response(store.create(values, notebook), status=201)

    async def import_project(request: web.Request) -> web.Response:
        require_mutation_header(request)
        data = await request.json()
        reference = str(data.get("project", "")).strip() if isinstance(data, dict) else ""
        if not reference:
            raise ValueError("Choose a project to import.")
        return web.json_response(store.import_project(reference), status=201)

    async def publish_post(request: web.Request) -> web.Response:
        require_mutation_header(request)
        result = await asyncio.to_thread(
            set_publication,
            store,
            publisher,
            request.match_info["slug"],
            draft=False,
        )
        return web.json_response(result)

    async def unpublish_post(request: web.Request) -> web.Response:
        require_mutation_header(request)
        result = await asyncio.to_thread(
            set_publication,
            store,
            publisher,
            request.match_info["slug"],
            draft=True,
        )
        return web.json_response(result)

    async def preview(request: web.Request) -> web.Response:
        require_mutation_header(request)
        return web.json_response(await asyncio.to_thread(publisher.preview))

    async def status(_request: web.Request) -> web.Response:
        return web.json_response(publisher.status)

    app.router.add_get("/admin", index)
    app.router.add_get("/admin/", index)
    app.router.add_get("/admin/assets/{name}", asset)
    app.router.add_get("/admin/api/posts", posts)
    app.router.add_get("/admin/api/projects", projects)
    app.router.add_post("/admin/api/posts", create_post)
    app.router.add_put("/admin/api/posts/{slug}", update_post)
    app.router.add_delete("/admin/api/posts/{slug}", delete_post)
    app.router.add_post("/admin/api/posts/{slug}/publish", publish_post)
    app.router.add_post("/admin/api/posts/{slug}/unpublish", unpublish_post)
    app.router.add_post("/admin/api/import", import_notebook)
    app.router.add_post("/admin/api/import-project", import_project)
    app.router.add_post("/admin/api/preview", preview)
    app.router.add_get("/admin/api/status", status)
    return app


def common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", default=os.environ.get("BLOG_SOURCE", "/home/rishabh/Projects/blog"))
    parser.add_argument("--state", default=os.environ.get("BLOG_STATE", "/srv/state/blog-site"))
    parser.add_argument("--preview-state", default=os.environ.get("BLOG_PREVIEW_STATE", ""))
    parser.add_argument("--quarto", default=os.environ.get("BLOG_QUARTO", shutil.which("quarto") or "quarto"))
    parser.add_argument("--rsync", default=os.environ.get("BLOG_RSYNC", shutil.which("rsync") or "rsync"))
    parser.add_argument("--resume", default=os.environ.get("BLOG_RESUME", ""))
    parser.add_argument(
        "--projectctl",
        default=os.environ.get("BLOG_PROJECTCTL", "/run/current-system/sw/bin/projectctl"),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the internal admin service")
    common_paths(serve)
    serve.add_argument("--assets", required=True)
    serve.add_argument("--editor-url", default=os.environ.get("BLOG_EDITOR_URL", ""))
    serve.add_argument("--public-url", default=os.environ.get("BLOG_PUBLIC_URL", ""))
    serve.add_argument("--preview-url", default=os.environ.get("BLOG_PREVIEW_URL", ""))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8792, type=int)

    build = subparsers.add_parser("build", help="render and deploy the blog")
    common_paths(build)

    preview = subparsers.add_parser("preview", help="run a local Quarto preview")
    common_paths(preview)
    preview.add_argument("--port", default=4200, type=int)

    listing = subparsers.add_parser("list", help="list posts")
    common_paths(listing)

    new = subparsers.add_parser("new", help="create a Markdown post")
    common_paths(new)
    new.add_argument("--title", required=True)
    new.add_argument("--slug")

    imported = subparsers.add_parser("import-notebook", help="import a Jupyter notebook")
    common_paths(imported)
    imported.add_argument("notebook")
    imported.add_argument("--title", required=True)
    imported.add_argument("--slug")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.source)
    store = BlogStore(
        source,
        getattr(args, "editor_url", ""),
        getattr(args, "public_url", ""),
        getattr(args, "preview_url", ""),
        args.projectctl,
    )

    if args.command == "serve":
        publisher = Publisher(
            source,
            Path(args.state),
            args.quarto,
            args.rsync,
            Path(args.resume) if args.resume else None,
            Path(args.preview_state) if args.preview_state else None,
            store,
        )
        web.run_app(
            create_app(store, publisher, Path(args.assets)),
            host=args.host,
            port=args.port,
            print=None,
        )
        return 0
    if args.command == "build":
        result = Publisher(
            source,
            Path(args.state),
            args.quarto,
            args.rsync,
            Path(args.resume) if args.resume else None,
            Path(args.preview_state) if args.preview_state else None,
            store,
        ).publish()
        if result["log"]:
            print(result["log"], end="" if result["log"].endswith("\n") else "\n")
        print(f"Published to {args.state}")
        return 0
    if args.command == "preview":
        os.execvp(args.quarto, [args.quarto, "preview", str(source), "--host", "127.0.0.1", "--port", str(args.port)])
    if args.command == "list":
        for post in store.list_posts():
            status = "draft" if post["draft"] else "published"
            print(f"{post['date']}  {status:9}  {post['kind']:8}  {post['slug']}")
        return 0
    if args.command == "new":
        post = store.create({"title": args.title, "slug": args.slug, "draft": True})
        print(source / post["source"])
        return 0
    if args.command == "import-notebook":
        notebook = Path(args.notebook).read_bytes()
        post = store.create({"title": args.title, "slug": args.slug, "draft": True}, notebook)
        print(source / post["source"])
        return 0
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as error:
        print(f"blogctl: {error}", file=sys.stderr)
        raise SystemExit(1) from error
