#!/usr/bin/env python3
"""Private gateway and CLI for purpose-scoped disposable inboxes."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import email.policy
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.parser import BytesParser
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable


APP_NAME = "Singlemail"
APP_VERSION = "0.1.0"
DEFAULT_API_URL = "https://singlemail.rishabhgoel0213.workers.dev"
DEFAULT_PUBLIC_URL = "https://maildrop.internal.therealrishabh.com"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8794
HTTP_TIMEOUT_SECONDS = 30
MAX_GATEWAY_BODY_BYTES = 16 * 1024
POLL_SECONDS = 2.0
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
NUMERIC_CODE_RE = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")
ALPHANUMERIC_CODE_RE = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{6,12})(?![A-Z0-9])")


class SinglemailError(RuntimeError):
    """A safe, user-facing Singlemail failure."""

    def __init__(
        self, message: str, status: int | None = None, code: str | None = None
    ):
        super().__init__(message)
        self.status = status
        self.code = code


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_bytes(value: Any) -> bytes:
    return compact_json(value).encode("utf-8")


def parse_duration(value: str) -> int:
    match = re.fullmatch(r"\s*(\d+)\s*([smhd]?)\s*", value.lower())
    if not match:
        raise argparse.ArgumentTypeError("duration must look like 30m, 2h, or 1d")
    amount = int(match.group(1))
    multiplier = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    seconds = amount * multiplier
    if seconds < 300 or seconds > 7 * 86400:
        raise argparse.ArgumentTypeError("duration must be between 5m and 7d")
    return seconds


def utc_iso(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return (
        dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )


def present_inbox(inbox: dict[str, Any]) -> dict[str, Any]:
    result = dict(inbox)
    for key in ("created_at", "expires_at", "closed_at"):
        result[f"{key}_iso"] = utc_iso(result.get(key))
    return result


class SafeHTMLText(HTMLParser):
    """Extract inert text and HTTP links without rendering active email HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "template", "svg", "math"}:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if lowered in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")
        if lowered == "a":
            attributes = {name.lower(): value for name, value in attrs}
            href = attributes.get("href")
            if href and href.lower().startswith(("http://", "https://")):
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "template", "svg", "math"}:
            self.ignored_depth = max(0, self.ignored_depth - 1)
            return
        if not self.ignored_depth and lowered in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)

    def result(self) -> str:
        lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in "".join(self.parts).splitlines()
        ]
        return "\n".join(line for line in lines if line)


def unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def message_text(message: EmailMessage) -> tuple[str, list[str]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    html_links: list[str] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError):
            payload = part.get_payload(decode=True) or b""
            content = payload.decode("utf-8", errors="replace")
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        if content_type == "text/plain":
            plain_parts.append(content)
        else:
            parser = SafeHTMLText()
            parser.feed(content)
            html_parts.append(parser.result())
            html_links.extend(parser.links)
    text = "\n\n".join(
        part.strip() for part in (plain_parts or html_parts) if part.strip()
    )
    return text[:250_000], html_links


def extract_links(text: str, extra: Iterable[str] = ()) -> list[str]:
    candidates = list(extra)
    for match in URL_RE.findall(text):
        candidates.append(match.rstrip(".,;:!?)]}"))
    return unique(candidates)


def extract_codes(subject: str, text: str) -> list[str]:
    source = f"{subject}\n{text}"
    candidates = list(NUMERIC_CODE_RE.findall(source))
    for candidate in ALPHANUMERIC_CODE_RE.findall(source.upper()):
        if any(character.isdigit() for character in candidate) and any(
            character.isalpha() for character in candidate
        ):
            candidates.append(candidate)
    return unique(candidates)


def parse_raw_message(raw: bytes) -> dict[str, Any]:
    parsed = BytesParser(policy=email.policy.default).parsebytes(raw)
    text, html_links = message_text(parsed)
    subject = str(parsed.get("subject", ""))
    return {
        "subject": subject,
        "from": str(parsed.get("from", "")),
        "to": str(parsed.get("to", "")),
        "date": str(parsed.get("date", "")),
        "message_id": str(parsed.get("message-id", "")),
        "text": text,
        "codes": extract_codes(subject, text),
        "links": extract_links(text, html_links),
    }


@dataclasses.dataclass(frozen=True)
class WorkerClient:
    api_url: str
    token: str
    timeout: int = HTTP_TIMEOUT_SECONDS

    @classmethod
    def from_environment(cls) -> "WorkerClient":
        api_url = os.environ.get("SINGLEMAIL_API_URL", DEFAULT_API_URL).rstrip("/")
        token = os.environ.get("SINGLEMAIL_API_TOKEN", "").strip()
        if not token:
            raise SinglemailError(
                "SINGLEMAIL_API_TOKEN is missing; deploy the SOPS secret or set it in the environment"
            )
        return cls(api_url=api_url, token=token)

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        raw: bool = False,
        authenticated: bool = True,
    ) -> Any:
        data = None if body is None else json_bytes(body)
        headers = {
            "Accept": "message/rfc822" if raw else "application/json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        }
        if authenticated:
            headers["Authorization"] = f"Bearer {self.token}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.api_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                if raw:
                    return payload
                if not payload:
                    return None
                return json.loads(payload)
        except urllib.error.HTTPError as error:
            payload = error.read()
            code = None
            message = f"Singlemail API returned HTTP {error.code}"
            try:
                detail = json.loads(payload)
                error_detail = detail.get("error", {})
                code = error_detail.get("code")
                message = error_detail.get("message", message)
            except (json.JSONDecodeError, AttributeError):
                pass
            raise SinglemailError(message, status=error.code, code=code) from error
        except urllib.error.URLError as error:
            raise SinglemailError(
                f"Could not reach Singlemail API: {error.reason}"
            ) from error

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/health", authenticated=False)

    def create(
        self, purpose: str, ttl_seconds: int, max_messages: int
    ) -> dict[str, Any]:
        result = self.request(
            "POST",
            "/v1/inboxes",
            {
                "purpose": purpose,
                "ttl_seconds": ttl_seconds,
                "max_messages": max_messages,
            },
        )
        return result["inbox"]

    def list(self, include_all: bool = False) -> list[dict[str, Any]]:
        suffix = "?status=all" if include_all else ""
        return self.request("GET", f"/v1/inboxes{suffix}")["inboxes"]

    def inbox(self, inbox_id: str) -> dict[str, Any]:
        return self.request("GET", f"/v1/inboxes/{urllib.parse.quote(inbox_id)}")[
            "inbox"
        ]

    def resolve(self, reference: str) -> dict[str, Any]:
        try:
            return self.inbox(reference)
        except SinglemailError as error:
            if error.status != HTTPStatus.NOT_FOUND:
                raise
        matches = [
            inbox
            for inbox in self.list(include_all=True)
            if inbox.get("address") == reference
        ]
        if len(matches) != 1:
            raise SinglemailError(
                f"Inbox not found: {reference}", status=HTTPStatus.NOT_FOUND
            )
        return matches[0]

    def messages(self, inbox_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        result = self.request(
            "GET", f"/v1/inboxes/{urllib.parse.quote(inbox_id)}/messages"
        )
        return result["inbox"], result["messages"]

    def raw_message(self, inbox_id: str, message_id: str) -> bytes:
        return self.request(
            "GET",
            f"/v1/inboxes/{urllib.parse.quote(inbox_id)}/messages/"
            f"{urllib.parse.quote(message_id)}/raw",
            raw=True,
        )

    def action(self, inbox_id: str, action: str) -> dict[str, Any]:
        return self.request(
            "POST", f"/v1/inboxes/{urllib.parse.quote(inbox_id)}/{action}", {}
        )["inbox"]

    def delete(self, inbox_id: str) -> None:
        self.request("DELETE", f"/v1/inboxes/{urllib.parse.quote(inbox_id)}")


def latest_parsed_message(client: WorkerClient, inbox_id: str) -> dict[str, Any] | None:
    _inbox, messages = client.messages(inbox_id)
    if not messages:
        return None
    metadata = messages[0]
    parsed = parse_raw_message(client.raw_message(inbox_id, metadata["id"]))
    return {"metadata": metadata, **parsed}


def wait_for_message(
    client: WorkerClient,
    inbox_id: str,
    timeout_seconds: int,
    required: str | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    observed_message_id: str | None = None
    while True:
        parsed = latest_parsed_message(client, inbox_id)
        if parsed is not None:
            observed_message_id = parsed["metadata"]["id"]
            if required is None or parsed.get(required):
                return parsed
        if time.monotonic() >= deadline:
            suffix = f" with {required}" if required else ""
            detail = (
                f"; latest message was {observed_message_id}"
                if observed_message_id
                else ""
            )
            raise SinglemailError(f"Timed out waiting for a message{suffix}{detail}")
        time.sleep(POLL_SECONDS)


def render_home() -> bytes:
    page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Singlemail</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#0b1020;color:#e8edf8}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at top,#172554 0,#0b1020 44rem)}
main{width:min(1040px,calc(100% - 2rem));margin:3rem auto}header{display:flex;justify-content:space-between;gap:2rem;align-items:end;margin-bottom:2rem}
h1{font-size:clamp(2rem,6vw,4rem);margin:0;letter-spacing:-.055em}.lede{color:#a9b5cc;max-width:42rem;line-height:1.6}
.panel{background:rgba(17,24,39,.86);border:1px solid #293653;border-radius:18px;padding:1.2rem;box-shadow:0 24px 70px #0006;margin-bottom:1rem}
form{display:grid;grid-template-columns:1fr 8rem 8rem auto;gap:.7rem}input,select,button{font:inherit;border-radius:10px;border:1px solid #3a4968;padding:.72rem .85rem}
input,select{background:#0c1428;color:#eef3ff}button{background:#3159d9;color:white;font-weight:700;cursor:pointer}button.secondary{background:#172036}button.danger{background:#8b2942}
.cards{display:grid;gap:.8rem}.card{border:1px solid #293653;border-radius:14px;padding:1rem;background:#0d1528}.row{display:flex;justify-content:space-between;gap:1rem;align-items:start;flex-wrap:wrap}
.address{font-family:ui-monospace,SFMono-Regular,monospace;color:#8fb4ff;overflow-wrap:anywhere}.muted{color:#91a0b9;font-size:.9rem}.actions{display:flex;gap:.45rem;flex-wrap:wrap}.actions button{padding:.45rem .65rem;font-size:.86rem}
.message{white-space:pre-wrap;background:#080d18;border-radius:10px;padding:1rem;line-height:1.5;max-height:22rem;overflow:auto}.hidden{display:none}.status{min-height:1.5rem;color:#f2c46d}
@media(max-width:720px){header{display:block}form{grid-template-columns:1fr 1fr}form input{grid-column:1/-1}}
</style>
</head>
<body><main>
<header><div><h1>Singlemail</h1><p class="lede">Purpose-scoped inboxes for private testing and authorized sign-in flows. Messages expire automatically.</p></div><div class="muted">inbox.therealrishabh.com</div></header>
<section class="panel"><form id="create"><input id="purpose" maxlength="200" required placeholder="Purpose, e.g. Example signup test"><select id="ttl"><option value="1800">30 min</option><option value="3600" selected>1 hour</option><option value="14400">4 hours</option><option value="86400">1 day</option></select><select id="max"><option>1</option><option selected>5</option><option>10</option></select><button>Create inbox</button></form><div id="status" class="status"></div></section>
<section id="inboxes" class="cards"></section>
</main>
<script>
const $=s=>document.querySelector(s);const esc=v=>String(v??'');
async function api(path,options={}){const r=await fetch(path,{headers:{'Content-Type':'application/json'},...options});if(!r.ok){const d=await r.json().catch(()=>({}));throw new Error(d.error?.message||`HTTP ${r.status}`)}return r.status===204?null:r.json()}
function button(label,cls,fn){const b=document.createElement('button');b.type='button';b.textContent=label;if(cls)b.className=cls;b.onclick=fn;return b}
async function load(){const data=await api('/api/inboxes');const root=$('#inboxes');root.replaceChildren();for(const inbox of data.inboxes){const card=document.createElement('article');card.className='card';const row=document.createElement('div');row.className='row';const info=document.createElement('div');const address=document.createElement('div');address.className='address';address.textContent=inbox.address;const purpose=document.createElement('strong');purpose.textContent=inbox.purpose;const meta=document.createElement('div');meta.className='muted';meta.textContent=`${inbox.message_count}/${inbox.max_messages} messages · expires ${new Date(inbox.expires_at*1000).toLocaleString()}`;info.append(address,purpose,meta);const actions=document.createElement('div');actions.className='actions';actions.append(button('Copy','secondary',()=>navigator.clipboard.writeText(inbox.address)),button('Messages','secondary',()=>messages(inbox.id,card)),button('Keep','secondary',async()=>{await api(`/api/inboxes/${inbox.id}/promote`,{method:'POST',body:'{}'});load()}),button('Close','danger',async()=>{await api(`/api/inboxes/${inbox.id}/close`,{method:'POST',body:'{}'});load()}));row.append(info,actions);card.append(row);root.append(card)}if(!data.inboxes.length){const empty=document.createElement('div');empty.className='panel muted';empty.textContent='No active inboxes.';root.append(empty)}}
async function messages(id,card){let box=card.querySelector('.message');if(box){box.remove();return}const data=await api(`/api/inboxes/${id}/messages`);box=document.createElement('div');box.className='message';if(!data.messages.length){box.textContent='No messages yet.'}else{for(const message of data.messages){const item=document.createElement('div');const title=document.createElement('strong');title.textContent=message.subject||'(no subject)';const details=document.createElement('div');details.className='muted';details.textContent=`From ${message.from} · ${new Date(message.received_at*1000).toLocaleString()}`;const body=document.createElement('div');body.textContent=message.text;item.append(title,details,body);if(message.codes.length){const codes=document.createElement('div');codes.className='address';codes.textContent=`Codes: ${message.codes.join(', ')}`;item.append(codes)}for(const url of message.links){const a=document.createElement('a');a.href=url;a.rel='noreferrer noopener';a.target='_blank';a.textContent=url;a.style.display='block';item.append(a)}box.append(item)}}card.append(box)}
$('#create').onsubmit=async e=>{e.preventDefault();const status=$('#status');status.textContent='Creating…';try{const data=await api('/api/inboxes',{method:'POST',body:JSON.stringify({purpose:$('#purpose').value,ttl_seconds:Number($('#ttl').value),max_messages:Number($('#max').value)})});status.textContent=`Created ${data.inbox.address}`;$('#purpose').value='';await load()}catch(err){status.textContent=err.message}};load().catch(err=>{$('#status').textContent=err.message});setInterval(()=>load().catch(()=>{}),15000);
</script></body></html>"""
    return page.encode("utf-8")


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "SinglemailGateway/0.1"

    @property
    def client(self) -> WorkerClient:
        return self.server.worker_client  # type: ignore[attr-defined]

    @property
    def public_url(self) -> str:
        return self.server.public_url  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(
            compact_json(
                {
                    "event": "http",
                    "client": self.client_address[0],
                    "method": self.command,
                    "path": urllib.parse.urlsplit(self.path).path,
                    "detail": fmt % args,
                }
            )
            + "\n"
        )

    def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, value: Any) -> None:
        self.send_bytes(status, json_bytes(value), "application/json; charset=utf-8")

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length < 0 or length > MAX_GATEWAY_BODY_BYTES:
            raise SinglemailError(
                "Request body is too large", status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE
            )
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as error:
            raise SinglemailError(
                "Request body must be valid JSON", status=HTTPStatus.BAD_REQUEST
            ) from error
        if not isinstance(value, dict):
            raise SinglemailError(
                "Request body must be an object", status=HTTPStatus.BAD_REQUEST
            )
        return value

    def require_same_origin(self) -> None:
        origin = self.headers.get("origin")
        if origin != self.public_url:
            raise SinglemailError(
                "Cross-origin request denied", status=HTTPStatus.FORBIDDEN
            )
        if self.headers.get_content_type() != "application/json":
            raise SinglemailError(
                "JSON content type required", status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE
            )

    def do_GET(self) -> None:  # noqa: N802
        try:
            self.handle_get()
        except SinglemailError as error:
            self.send_json(
                error.status or 502,
                {"error": {"code": error.code, "message": str(error)}},
            )
        except Exception as error:  # pragma: no cover - defensive server boundary
            sys.stderr.write(
                compact_json({"event": "gateway_error", "detail": str(error)}) + "\n"
            )
            self.send_json(500, {"error": {"message": "Internal gateway error"}})

    def handle_get(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        segments = [urllib.parse.unquote(value) for value in path.split("/") if value]
        if path == "/":
            self.send_bytes(200, render_home(), "text/html; charset=utf-8")
            return
        if path == "/health":
            self.send_json(
                200,
                {
                    "ready": bool(self.client.health().get("ready")),
                    "service": "singlemail-gateway",
                },
            )
            return
        if path == "/api/inboxes":
            self.send_json(200, {"inboxes": self.client.list()})
            return
        if (
            len(segments) == 4
            and segments[:2] == ["api", "inboxes"]
            and segments[3] == "messages"
        ):
            inbox, messages = self.client.messages(segments[2])
            rendered = []
            for message in messages:
                parsed = parse_raw_message(
                    self.client.raw_message(segments[2], message["id"])
                )
                rendered.append({**message, **parsed})
            self.send_json(200, {"inbox": inbox, "messages": rendered})
            return
        self.send_json(404, {"error": {"message": "Not found"}})

    def do_POST(self) -> None:  # noqa: N802
        try:
            self.require_same_origin()
            self.handle_post()
        except SinglemailError as error:
            self.send_json(
                error.status or 502,
                {"error": {"code": error.code, "message": str(error)}},
            )
        except Exception as error:  # pragma: no cover - defensive server boundary
            sys.stderr.write(
                compact_json({"event": "gateway_error", "detail": str(error)}) + "\n"
            )
            self.send_json(500, {"error": {"message": "Internal gateway error"}})

    def handle_post(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        segments = [urllib.parse.unquote(value) for value in path.split("/") if value]
        body = self.read_json()
        if path == "/api/inboxes":
            purpose = body.get("purpose")
            ttl = body.get("ttl_seconds")
            maximum = body.get("max_messages")
            if (
                not isinstance(purpose, str)
                or not isinstance(ttl, int)
                or not isinstance(maximum, int)
            ):
                raise SinglemailError(
                    "Invalid inbox parameters", status=HTTPStatus.BAD_REQUEST
                )
            inbox = self.client.create(purpose, ttl, maximum)
            self.send_json(201, {"inbox": inbox})
            return
        if (
            len(segments) == 4
            and segments[:2] == ["api", "inboxes"]
            and segments[3] in {"close", "promote"}
        ):
            inbox = self.client.action(segments[2], segments[3])
            self.send_json(200, {"inbox": inbox})
            return
        self.send_json(404, {"error": {"message": "Not found"}})


class GatewayServer(ThreadingHTTPServer):
    worker_client: WorkerClient
    public_url: str


def run_server(args: argparse.Namespace) -> None:
    server = GatewayServer((args.host, args.port), GatewayHandler)
    server.worker_client = WorkerClient.from_environment()
    server.public_url = args.public_url.rstrip("/")
    print(
        compact_json({"event": "listening", "host": args.host, "port": args.port}),
        flush=True,
    )
    server.serve_forever()


def emit(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))


def run_cli(args: argparse.Namespace) -> None:
    if args.command == "serve":
        run_server(args)
        return
    client = WorkerClient.from_environment()
    if args.command == "doctor":
        health = client.health()
        inboxes = client.list()
        emit(
            {
                "healthy": health.get("ready") is True,
                "api": client.api_url,
                "active_inboxes": len(inboxes),
            },
            args.json,
        )
        return
    if args.command == "create":
        inbox = client.create(args.purpose, args.ttl, args.max_messages)
        emit(present_inbox(inbox) if args.json else inbox["address"], args.json)
        return
    if args.command == "list":
        inboxes = [present_inbox(inbox) for inbox in client.list(args.all)]
        if args.json:
            emit({"inboxes": inboxes}, True)
        else:
            for inbox in inboxes:
                state = "active" if inbox["active"] else "closed"
                print(f"{inbox['id']}  {inbox['address']}  {state}  {inbox['purpose']}")
        return

    inbox = client.resolve(args.inbox)
    inbox_id = inbox["id"]
    if args.command == "messages":
        _inbox, messages = client.messages(inbox_id)
        emit({"inbox": present_inbox(inbox), "messages": messages}, args.json)
    elif args.command == "wait":
        emit(wait_for_message(client, inbox_id, args.timeout), args.json)
    elif args.command == "read":
        parsed = latest_parsed_message(client, inbox_id)
        if parsed is None:
            raise SinglemailError("Inbox has no messages")
        emit(parsed, args.json)
    elif args.command == "code":
        parsed = wait_for_message(client, inbox_id, args.timeout, required="codes")
        emit(parsed if args.json else parsed["codes"][0], args.json)
    elif args.command == "links":
        parsed = wait_for_message(client, inbox_id, args.timeout, required="links")
        emit(parsed if args.json else "\n".join(parsed["links"]), args.json)
    elif args.command in {"close", "promote"}:
        emit(present_inbox(client.action(inbox_id, args.command)), args.json)
    elif args.command == "delete":
        client.delete(inbox_id)
        emit({"deleted": True, "id": inbox_id}, args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {APP_VERSION}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the private web gateway")
    serve.add_argument(
        "--host", default=os.environ.get("SINGLEMAIL_HOST", DEFAULT_HOST)
    )
    serve.add_argument(
        "--port", type=int, default=int(os.environ.get("SINGLEMAIL_PORT", DEFAULT_PORT))
    )
    serve.add_argument(
        "--public-url",
        default=os.environ.get("SINGLEMAIL_PUBLIC_URL", DEFAULT_PUBLIC_URL),
    )

    for name, help_text in [
        ("doctor", "check Worker and database health"),
        ("list", "list inboxes"),
    ]:
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--json", action="store_true")
        if name == "list":
            command.add_argument("--all", action="store_true")

    create = subparsers.add_parser("create", help="create a purpose-scoped inbox")
    create.add_argument("--purpose", required=True)
    create.add_argument("--ttl", type=parse_duration, default=3600, metavar="DURATION")
    create.add_argument("--max-messages", type=int, choices=range(1, 21), default=5)
    create.add_argument("--json", action="store_true")

    for name, help_text in [
        ("messages", "list message metadata"),
        ("read", "read the latest message as safe text"),
        ("close", "stop accepting mail for an inbox"),
        ("promote", "keep an address active for account recovery"),
        ("delete", "delete an inbox and its messages"),
    ]:
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("inbox", help="inbox ID or full address")
        command.add_argument("--json", action="store_true")

    for name, help_text in [
        ("wait", "wait for the first message"),
        ("code", "wait for and print the first verification code"),
        ("links", "wait for and print verification links"),
    ]:
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("inbox", help="inbox ID or full address")
        command.add_argument(
            "--timeout", type=parse_duration, default=300, metavar="DURATION"
        )
        command.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        run_cli(args)
        return 0
    except SinglemailError as error:
        print(f"singlemail: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
