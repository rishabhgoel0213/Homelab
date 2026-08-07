#!/usr/bin/env python3
"""Minimal read-only Expo Updates Protocol v1 server for T3 Code Android."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import urllib.parse
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


def digest(path: Path, algorithm: str) -> bytes:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.digest()


def update_id(metadata_path: Path) -> str:
    value = hashlib.sha256(metadata_path.read_bytes()).hexdigest()[:32]
    return str(uuid.UUID(value))


def iso_timestamp(path: Path) -> str:
    value = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def multipart(parts: list[tuple[str, dict[str, Any]]]) -> tuple[str, bytes]:
    boundary = f"expo-{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in parts:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n'.encode())
        body.extend(b"Content-Type: application/json; charset=utf-8\r\n\r\n")
        body.extend(json.dumps(value, separators=(",", ":")).encode())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return boundary, bytes(body)


class UpdatesHandler(BaseHTTPRequestHandler):
    server_version = "T3CodeUpdates/1"

    @property
    def updates_root(self) -> Path:
        return self.server.updates_root  # type: ignore[attr-defined]

    @property
    def public_url(self) -> str:
        return self.server.public_url  # type: ignore[attr-defined]

    @property
    def bootstrap_apk(self) -> Path:
        return self.server.bootstrap_apk  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/healthz":
                self.send_json(HTTPStatus.OK, {"status": "ok"})
            elif parsed.path == "/":
                self.send_index()
            elif parsed.path == "/api/manifest":
                self.send_manifest(urllib.parse.parse_qs(parsed.query))
            elif parsed.path == "/api/assets":
                self.send_asset(urllib.parse.parse_qs(parsed.query))
            elif parsed.path == "/bootstrap.apk":
                self.send_bootstrap()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": str(error)})

    def send_index(self) -> None:
        runtimes = []
        if self.updates_root.is_dir():
            runtimes = sorted(path.name for path in self.updates_root.iterdir() if path.is_dir())
        self.send_json(
            HTTPStatus.OK,
            {
                "service": "T3 Code private Expo Updates",
                "runtimes": runtimes,
                "bootstrapApk": f"{self.public_url}/bootstrap.apk"
                if self.bootstrap_apk.is_file()
                else None,
            },
        )

    def send_manifest(self, query: dict[str, list[str]]) -> None:
        protocol = self.headers.get("expo-protocol-version", "0")
        if protocol not in {"0", "1"}:
            raise ValueError("unsupported Expo protocol version")
        platform = self.headers.get("expo-platform") or first(query, "platform")
        runtime = self.headers.get("expo-runtime-version") or first(query, "runtime-version")
        if platform != "android":
            raise ValueError("only the Android update channel is available")
        if not runtime or not SAFE_COMPONENT.fullmatch(runtime):
            raise ValueError("invalid or missing Expo runtime version")

        runtime_root = self.updates_root / runtime
        releases = sorted(
            (path for path in runtime_root.iterdir() if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
        if not releases:
            raise ValueError("no update exists for this runtime version")
        release = releases[0]
        metadata_path = release / "metadata.json"
        config_path = release / "expoConfig.json"
        metadata = json.loads(metadata_path.read_text())
        expo_config = json.loads(config_path.read_text())
        identifier = update_id(metadata_path)

        if protocol == "1" and self.headers.get("expo-current-update-id") == identifier:
            boundary, body = multipart([("directive", {"type": "noUpdateAvailable"})])
            self.send_multipart(protocol, boundary, body)
            return

        platform_metadata = metadata["fileMetadata"][platform]
        assets = [
            self.asset_metadata(release, item["path"], item["ext"], runtime, False)
            for item in platform_metadata["assets"]
        ]
        launch_asset = self.asset_metadata(
            release, platform_metadata["bundle"], "bundle", runtime, True
        )
        manifest = {
            "id": identifier,
            "createdAt": iso_timestamp(metadata_path),
            "runtimeVersion": runtime,
            "assets": assets,
            "launchAsset": launch_asset,
            "metadata": {},
            "extra": {"expoClient": expo_config},
        }
        request_headers = {asset["key"]: {} for asset in [*assets, launch_asset]}
        boundary, body = multipart(
            [("manifest", manifest), ("extensions", {"assetRequestHeaders": request_headers})]
        )
        self.send_multipart(protocol, boundary, body)

    def asset_metadata(
        self,
        release: Path,
        relative_path: str,
        extension: str,
        runtime: str,
        launch: bool,
    ) -> dict[str, str]:
        asset = safe_child(release, relative_path)
        sha256 = base64.urlsafe_b64encode(digest(asset, "sha256")).decode().rstrip("=")
        key = digest(asset, "md5").hex()  # Expo protocol asset key, not security-sensitive.
        content_type = "application/javascript" if launch else mimetypes.guess_type(f"x.{extension}")[0]
        query = urllib.parse.urlencode(
            {"runtimeVersion": runtime, "release": release.name, "path": relative_path}
        )
        return {
            "hash": sha256,
            "key": key,
            "fileExtension": f".{extension}",
            "contentType": content_type or "application/octet-stream",
            "url": f"{self.public_url}/api/assets?{query}",
        }

    def send_asset(self, query: dict[str, list[str]]) -> None:
        runtime = first(query, "runtimeVersion")
        release_name = first(query, "release")
        relative_path = first(query, "path")
        if not runtime or not release_name or not relative_path:
            raise ValueError("missing asset coordinates")
        if not SAFE_COMPONENT.fullmatch(runtime) or not SAFE_COMPONENT.fullmatch(release_name):
            raise ValueError("invalid asset coordinates")
        release = self.updates_root / runtime / release_name
        asset = safe_child(release, relative_path)
        content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
        if asset.suffix == ".hbc":
            content_type = "application/javascript"
        self.send_file(asset, content_type, "public, max-age=31536000, immutable")

    def send_bootstrap(self) -> None:
        self.send_file(
            self.bootstrap_apk,
            "application/vnd.android.package-archive",
            "private, max-age=0",
        )

    def send_file(self, path: Path, content_type: str, cache_control: str) -> None:
        size = path.stat().st_size
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                self.wfile.write(chunk)

    def send_multipart(self, protocol: str, boundary: str, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"multipart/mixed; boundary={boundary}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=0")
        self.send_header("Expo-Protocol-Version", protocol)
        self.send_header("Expo-SFV-Version", "0")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def first(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    return values[0] if values else None


def safe_child(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    candidate = (root / relative_path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise ValueError("invalid asset path")
    return candidate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--updates-root", type=Path, required=True)
    parser.add_argument("--bootstrap-apk", type=Path, required=True)
    parser.add_argument("--public-url", required=True)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), UpdatesHandler)
    server.updates_root = args.updates_root.resolve()  # type: ignore[attr-defined]
    server.bootstrap_apk = args.bootstrap_apk.resolve()  # type: ignore[attr-defined]
    server.public_url = args.public_url.rstrip("/")  # type: ignore[attr-defined]
    server.serve_forever()


if __name__ == "__main__":
    main()
