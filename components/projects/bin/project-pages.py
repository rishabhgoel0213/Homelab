#!/usr/bin/env python3
"""Read-only project files behind the private Caddy ingress; no listings or CGI."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from aiohttp import web


class ExactFileResponse(web.FileResponse):
    async def prepare(self, request):
        # Caddy handles compression. Do not let FileResponse select an unchecked
        # .gz/.br neighbor, which might itself be a symlink outside the root.
        headers = request.headers.copy()
        headers.popall("Accept-Encoding", None)
        return await super().prepare(request.clone(headers=headers))


def create_app(root: Path) -> web.Application:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("The project root must be a directory")

    def checked_file(path: Path) -> Path:
        try:
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(root)
            if any(part.startswith(".") for part in relative.parts):
                raise web.HTTPNotFound()
            if not resolved.is_file():
                raise web.HTTPNotFound()
            return resolved
        except (OSError, ValueError, RuntimeError):
            raise web.HTTPNotFound() from None

    async def serve(request: web.Request) -> web.StreamResponse:
        relative = request.match_info["path"]
        if "\x00" in relative or any(part.startswith(".") for part in relative.split("/")):
            raise web.HTTPNotFound()
        candidate = root / relative
        try:
            is_directory = candidate.is_dir()
        except (OSError, ValueError):
            raise web.HTTPNotFound() from None
        path = checked_file(candidate / "index.html" if is_directory else candidate)
        if is_directory and not request.path.endswith("/"):
            raise web.HTTPPermanentRedirect(
                location=str(request.rel_url.with_path(request.path + "/", keep_query=True))
            )
        return ExactFileResponse(
            path,
            headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )

    app = web.Application()
    app.router.add_get("/{path:.*}", serve)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8795)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(args.root), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
