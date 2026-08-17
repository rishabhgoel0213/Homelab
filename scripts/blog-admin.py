#!/usr/bin/env python3
"""Manage and publish the private Quarto blog."""

from __future__ import annotations

import argparse
import asyncio
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

    for post_dir in posts_source.iterdir():
        if not post_dir.is_dir() or not SLUG_RE.fullmatch(post_dir.name):
            continue
        metadata_path = post_dir / "_metadata.yml"
        metadata = (
            yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
            if metadata_path.is_file()
            else {}
        )
        if isinstance(metadata, dict) and bool(metadata.get("draft", False)):
            rendered = (posts_output / post_dir.name).resolve()
            if rendered.parent == posts_output:
                shutil.rmtree(rendered, ignore_errors=True)


def install_resume(resume: Path | None, output: Path) -> None:
    if resume is None:
        return
    if not resume.is_file():
        raise RuntimeError(f"Resume does not exist: {resume}")
    shutil.copy2(resume, output / "rishabh-goel-resume.pdf")


class BlogStore:
    def __init__(
        self,
        source: Path,
        editor_url: str = "",
        public_url: str = "",
        preview_url: str = "",
    ) -> None:
        self.source = source.resolve()
        self.posts = self.source / "posts"
        self.editor_url = editor_url.rstrip("/")
        self.public_url = public_url.rstrip("/")
        self.preview_url = preview_url.rstrip("/")

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
            "slug": post_dir.name,
            "title": str(metadata.get("title", post_dir.name)),
            "date": str(metadata.get("date", "")),
            "description": str(metadata.get("description", "")),
            "categories": categories,
            "draft": draft,
            "kind": kind,
            "source": relative_source,
            "editorUrl": f"{self.editor_url}/lab/tree{editor_path}" if self.editor_url else "",
            "postUrl": f"{post_base_url}/posts/{post_dir.name}/"
            if post_base_url
            else f"/posts/{post_dir.name}/",
        }

    def list_posts(self) -> list[dict[str, Any]]:
        self.ensure()
        result = [self.describe(path) for path in self.posts.iterdir() if path.is_dir()]
        return sorted(result, key=lambda post: (post["date"], post["slug"]), reverse=True)

    def create(self, data: dict[str, Any], notebook: bytes | None = None) -> dict[str, Any]:
        self.ensure()
        metadata = normalize_metadata(data)
        slug = validate_slug(str(data.get("slug") or slugify(metadata["title"])))
        post_dir = self.post_dir(slug)
        if post_dir.exists():
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

    def update(self, slug: str, data: dict[str, Any]) -> dict[str, Any]:
        post_dir = self.post_dir(slug)
        if not post_dir.is_dir():
            raise FileNotFoundError(f"Post '{slug}' does not exist.")
        metadata = normalize_metadata(data)
        atomic_write(post_dir / "_metadata.yml", metadata_text(metadata))
        return self.describe(post_dir)


class Publisher:
    def __init__(
        self,
        source: Path,
        state: Path,
        quarto: str,
        rsync: str,
        resume: Path | None = None,
        preview_state: Path | None = None,
    ) -> None:
        self.source = source.resolve()
        self.state = state.resolve()
        self.quarto = quarto
        self.rsync = rsync
        self.resume = resume.resolve() if resume else None
        self.preview_state = preview_state.resolve() if preview_state else None
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
            ignore=shutil.ignore_patterns(".git", ".quarto", "_site", "__pycache__", "*.pyc"),
        )

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
        return web.FileResponse(assets / "index.html")

    async def asset(request: web.Request) -> web.FileResponse:
        name = request.match_info["name"]
        if name not in {"app.js", "styles.css"}:
            raise web.HTTPNotFound()
        return web.FileResponse(assets / name)

    async def posts(_request: web.Request) -> web.Response:
        return web.json_response({"posts": store.list_posts()})

    async def create_post(request: web.Request) -> web.Response:
        require_mutation_header(request)
        return web.json_response(store.create(await request.json()), status=201)

    async def update_post(request: web.Request) -> web.Response:
        require_mutation_header(request)
        return web.json_response(store.update(request.match_info["slug"], await request.json()))

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

    async def publish(request: web.Request) -> web.Response:
        require_mutation_header(request)
        return web.json_response(await asyncio.to_thread(publisher.publish))

    async def preview(request: web.Request) -> web.Response:
        require_mutation_header(request)
        return web.json_response(await asyncio.to_thread(publisher.preview))

    async def status(_request: web.Request) -> web.Response:
        return web.json_response(publisher.status)

    app.router.add_get("/admin", index)
    app.router.add_get("/admin/", index)
    app.router.add_get("/admin/assets/{name}", asset)
    app.router.add_get("/admin/api/posts", posts)
    app.router.add_post("/admin/api/posts", create_post)
    app.router.add_put("/admin/api/posts/{slug}", update_post)
    app.router.add_post("/admin/api/import", import_notebook)
    app.router.add_post("/admin/api/preview", preview)
    app.router.add_post("/admin/api/publish", publish)
    app.router.add_get("/admin/api/status", status)
    return app


def common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", default=os.environ.get("BLOG_SOURCE", "/home/rishabh/Projects/blog"))
    parser.add_argument("--state", default=os.environ.get("BLOG_STATE", "/srv/state/blog-site"))
    parser.add_argument("--preview-state", default=os.environ.get("BLOG_PREVIEW_STATE", ""))
    parser.add_argument("--quarto", default=os.environ.get("BLOG_QUARTO", shutil.which("quarto") or "quarto"))
    parser.add_argument("--rsync", default=os.environ.get("BLOG_RSYNC", shutil.which("rsync") or "rsync"))
    parser.add_argument("--resume", default=os.environ.get("BLOG_RESUME", ""))


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
    )

    if args.command == "serve":
        publisher = Publisher(
            source,
            Path(args.state),
            args.quarto,
            args.rsync,
            Path(args.resume) if args.resume else None,
            Path(args.preview_state) if args.preview_state else None,
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
