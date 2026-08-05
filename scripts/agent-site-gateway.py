#!/usr/bin/env python3
"""Proxy registered task-local web servers onto short-lived internal hostnames."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout, WSMsgType, web


HOST_LABEL_RE = re.compile(r"task-[a-z0-9](?:[a-z0-9-]*[a-z0-9])?-[0-9a-f]{8}")
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def read_manifest(work_dir: Path) -> dict[str, Any] | None:
    try:
        value = json.loads((work_dir / ".agent-work.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def resolve_site(
    host: str,
    registry: Path,
    work_root: Path,
    domain: str,
    current_time: datetime | None = None,
) -> dict[str, Any] | None:
    hostname = host.partition(":")[0].lower().rstrip(".")
    suffix = f".{domain.lower().strip('.')}"
    if not hostname.endswith(suffix) or not HOST_LABEL_RE.fullmatch(hostname.removesuffix(suffix)):
        return None
    try:
        value = json.loads(registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    sites = value.get("sites") if isinstance(value, dict) else None
    if not isinstance(sites, list):
        return None

    root = work_root.resolve()
    now = current_time or datetime.now(UTC)
    for entry in sites:
        if not isinstance(entry, dict) or entry.get("host") != hostname:
            continue
        port = entry.get("port")
        expires_at = entry.get("expires_at")
        task_id = entry.get("task_id")
        work_dir_raw = entry.get("work_dir")
        if (
            not isinstance(port, int)
            or port <= 0
            or port > 65535
            or not isinstance(expires_at, str)
            or not isinstance(task_id, str)
            or not isinstance(work_dir_raw, str)
        ):
            return None
        try:
            if parse_time(expires_at) <= now:
                return None
            untrusted_work_dir = Path(work_dir_raw)
            if untrusted_work_dir.is_symlink():
                return None
            work_dir = untrusted_work_dir.resolve()
        except (OSError, ValueError):
            return None
        if work_dir.parent != root or not work_dir.is_dir():
            return None
        manifest = read_manifest(work_dir)
        if manifest is None or manifest.get("id") != task_id:
            return None
        return entry
    return None


def forwarded_headers(request: web.Request, port: int, websocket: bool = False) -> list[tuple[str, str]]:
    headers = []
    for name, value in request.headers.items():
        lowered = name.lower()
        if lowered == "host" or lowered in HOP_BY_HOP_HEADERS:
            continue
        if websocket and lowered.startswith("sec-websocket-"):
            continue
        headers.append((name, value))
    headers.extend(
        [
            ("Host", f"127.0.0.1:{port}"),
            ("X-Forwarded-Host", request.host),
            ("X-Forwarded-Proto", "https"),
        ]
    )
    return headers


def response_headers(headers: Any, host: str, port: int) -> list[tuple[str, str]]:
    result = []
    for name, value in headers.items():
        if name.lower() in HOP_BY_HOP_HEADERS:
            continue
        if name.lower() == "location":
            for local_host in ("127.0.0.1", "localhost"):
                value = value.replace(f"http://{local_host}:{port}", f"https://{host}")
        result.append((name, value))
    return result


async def relay_websocket(source: Any, destination: Any) -> None:
    async for message in source:
        if message.type == WSMsgType.TEXT:
            await destination.send_str(message.data)
        elif message.type == WSMsgType.BINARY:
            await destination.send_bytes(message.data)
        elif message.type == WSMsgType.PING:
            await destination.ping(message.data)
        elif message.type == WSMsgType.PONG:
            await destination.pong(message.data)
        elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
            break


async def proxy_websocket(request: web.Request, session: ClientSession, port: int) -> web.StreamResponse:
    protocols = tuple(
        protocol.strip()
        for protocol in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
        if protocol.strip()
    )
    upstream_url = f"ws://127.0.0.1:{port}{request.raw_path}"
    try:
        upstream = await session.ws_connect(
            upstream_url,
            headers=forwarded_headers(request, port, websocket=True),
            protocols=protocols,
            autoclose=True,
            autoping=True,
        )
    except (ClientError, OSError) as error:
        raise web.HTTPBadGateway(text="The temporary site is not currently reachable.") from error

    downstream = web.WebSocketResponse(protocols=protocols, autoclose=True, autoping=True)
    await downstream.prepare(request)
    tasks = {
        asyncio.create_task(relay_websocket(downstream, upstream)),
        asyncio.create_task(relay_websocket(upstream, downstream)),
    }
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done | pending:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    await upstream.close()
    await downstream.close()
    return downstream


async def proxy(request: web.Request) -> web.StreamResponse:
    settings = request.app["settings"]
    entry = resolve_site(
        request.host,
        settings["registry"],
        settings["work_root"],
        settings["domain"],
    )
    if entry is None:
        raise web.HTTPNotFound(text="No temporary internal site is registered for this hostname.")
    port = int(entry["port"])
    session = request.app["client_session"]
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await proxy_websocket(request, session, port)

    upstream_url = f"http://127.0.0.1:{port}{request.raw_path}"
    try:
        upstream = await session.request(
            request.method,
            upstream_url,
            headers=forwarded_headers(request, port),
            data=request.content if request.can_read_body else None,
            allow_redirects=False,
        )
    except (ClientError, OSError) as error:
        raise web.HTTPBadGateway(text="The temporary site is not currently reachable.") from error

    downstream = web.StreamResponse(
        status=upstream.status,
        reason=upstream.reason,
        headers=response_headers(upstream.headers, request.host, port),
    )
    await downstream.prepare(request)
    try:
        async for chunk in upstream.content.iter_chunked(64 * 1024):
            await downstream.write(chunk)
    finally:
        upstream.release()
    await downstream.write_eof()
    return downstream


async def create_client_session(app: web.Application) -> None:
    timeout = ClientTimeout(total=None, sock_connect=3, sock_read=None)
    app["client_session"] = ClientSession(timeout=timeout)


async def close_client_session(app: web.Application) -> None:
    await app["client_session"].close()


def build_app() -> web.Application:
    app = web.Application(client_max_size=1024**3)
    app["settings"] = {
        "registry": Path(os.environ.get("AGENT_SITE_REGISTRY", "/srv/state/agents/sites.json")),
        "work_root": Path(os.environ.get("AGENT_WORK_ROOT", "/var/tmp/agent-work")),
        "domain": os.environ.get("AGENT_SITE_DOMAIN", "internal.therealrishabh.com"),
    }
    app.on_startup.append(create_client_session)
    app.on_cleanup.append(close_client_session)
    app.router.add_route("*", "/{path:.*}", proxy)
    return app


def main() -> None:
    port = int(os.environ.get("AGENT_SITE_GATEWAY_PORT", "7780"))
    web.run_app(build_app(), host="127.0.0.1", port=port, access_log=None)


if __name__ == "__main__":
    main()
