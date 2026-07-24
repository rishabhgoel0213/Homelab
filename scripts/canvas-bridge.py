#!/usr/bin/env python3
"""Read-only UMD Canvas bridge with a private web bootstrap and MCP tools."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import hmac
import html
import json
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree


APP_NAME = "UMD Canvas Bridge"
APP_VERSION = "0.1.0"
CANVAS_BASE_URL = os.environ.get("CANVAS_BRIDGE_CANVAS_URL", "https://umd.instructure.com").rstrip("/")
MOBILE_VERIFY_URL = "https://sso.canvaslms.com/api/v1/mobile_verify.json"
MOBILE_USER_AGENT = "candroid"
AUTHORIZATION_REDIRECT_URI = "https://sso.canvaslms.com/canvas/login"
TOKEN_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
STATE_DIR = Path(os.environ.get("CANVAS_BRIDGE_STATE_DIR", "/srv/state/canvas-bridge"))
DATABASE_PATH = STATE_DIR / "canvas.db"
FILES_DIR = STATE_DIR / "files"
LOCK_PATH = STATE_DIR / "sync.lock"
LISTEN_HOST = os.environ.get("CANVAS_BRIDGE_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("CANVAS_BRIDGE_PORT", "8793"))
PUBLIC_URL = os.environ.get(
    "CANVAS_BRIDGE_PUBLIC_URL",
    "https://canvas.internal.therealrishabh.com",
).rstrip("/")
SYNC_INTERVAL_SECONDS = int(os.environ.get("CANVAS_BRIDGE_SYNC_INTERVAL", "900"))
MAX_FILE_BYTES = int(os.environ.get("CANVAS_BRIDGE_MAX_FILE_BYTES", str(50 * 1024 * 1024)))
MAX_FILES_PER_COURSE = int(os.environ.get("CANVAS_BRIDGE_MAX_FILES_PER_COURSE", "300"))
PAIRING_TTL_SECONDS = 10 * 60
OAUTH_STATE_TTL_SECONDS = 20 * 60
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
HTTP_TIMEOUT_SECONDS = 45

DOWNLOADABLE_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/rtf",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "text/csv",
    "text/html",
    "text/markdown",
    "text/plain",
    "text/x-c",
    "text/x-c++",
    "text/x-java-source",
    "text/x-python",
}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    FILES_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(STATE_DIR, 0o700)
        os.chmod(FILES_DIR, 0o700)
    except OSError:
        pass


def connect_db() -> sqlite3.Connection:
    ensure_state_dir()
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    initialize_schema(connection)
    return connection


@contextlib.contextmanager
def db_session() -> Iterable[sqlite3.Connection]:
    connection = connect_db()
    try:
        yield connection
    finally:
        connection.close()


def initialize_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS auth (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            canvas_url TEXT NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT NOT NULL,
            user_json TEXT NOT NULL,
            connected_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pending_oauth (
            state_hash TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS web_sessions (
            session_hash TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pairing_codes (
            code_hash TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS courses (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            course_code TEXT,
            term_name TEXT,
            start_at TEXT,
            end_at TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            json TEXT NOT NULL,
            synced_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS modules (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            name TEXT NOT NULL,
            position INTEGER,
            state TEXT,
            unlock_at TEXT,
            json TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS module_items (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            module_id TEXT NOT NULL,
            title TEXT NOT NULL,
            type TEXT,
            position INTEGER,
            content_id TEXT,
            page_url TEXT,
            html_url TEXT,
            external_url TEXT,
            completion_requirement TEXT,
            json TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE,
            FOREIGN KEY(module_id) REFERENCES modules(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS documents (
            kind TEXT NOT NULL,
            course_id TEXT NOT NULL,
            object_id TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            html_url TEXT,
            due_at TEXT,
            updated_at TEXT,
            local_path TEXT,
            metadata_json TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            PRIMARY KEY(kind, course_id, object_id),
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sync_status (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            state TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            error TEXT,
            summary_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_modules_course_position
            ON modules(course_id, position);
        CREATE INDEX IF NOT EXISTS idx_items_course_module_position
            ON module_items(course_id, module_id, position);
        CREATE INDEX IF NOT EXISTS idx_documents_course_kind
            ON documents(course_id, kind);
        CREATE INDEX IF NOT EXISTS idx_documents_due_at
            ON documents(due_at);
        """
    )
    db.commit()
    try:
        os.chmod(DATABASE_PATH, 0o600)
    except FileNotFoundError:
        pass


def get_setting(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else None


def set_setting(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_or_create_cookie_secret(db: sqlite3.Connection) -> bytes:
    value = get_setting(db, "cookie_secret")
    if not value:
        value = secrets.token_urlsafe(48)
        set_setting(db, "cookie_secret", value)
        db.commit()
    return value.encode()


class TextExtractor(HTMLParser):
    BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg"}:
            self.hidden_depth += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts))
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n[ \t]+", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    parser = TextExtractor()
    with contextlib.suppress(Exception):
        parser.feed(value)
        return parser.text()
    return re.sub(r"<[^>]+>", " ", value).strip()


def safe_filename(value: str, fallback: str = "file") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or fallback)[:180]


def extract_openxml(path: Path) -> str:
    patterns = (
        "word/document.xml",
        "ppt/slides/slide*.xml",
        "xl/sharedStrings.xml",
        "xl/worksheets/sheet*.xml",
    )
    parts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        selected: list[str] = []
        for pattern in patterns:
            if "*" not in pattern and pattern in names:
                selected.append(pattern)
            elif "*" in pattern:
                prefix, suffix = pattern.split("*", 1)
                selected.extend(sorted(name for name in names if name.startswith(prefix) and name.endswith(suffix)))
        for name in selected:
            try:
                root = ElementTree.fromstring(archive.read(name))
            except (ElementTree.ParseError, KeyError):
                continue
            text_nodes = [node.text or "" for node in root.iter() if node.tag.rsplit("}", 1)[-1] in {"t", "v"}]
            if text_nodes:
                parts.append(" ".join(text_nodes))
    return "\n\n".join(parts).strip()


def extract_file_text(path: Path, content_type: str) -> str:
    suffix = path.suffix.lower()
    if content_type.startswith("text/") or suffix in {".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm"}:
        raw = path.read_bytes()[:10 * 1024 * 1024]
        value = raw.decode("utf-8", errors="replace")
        return html_to_text(value) if suffix in {".html", ".htm"} or content_type in {"text/html", "application/xhtml+xml"} else value
    if content_type == "application/pdf" or suffix == ".pdf":
        executable = shutil.which("pdftotext")
        if not executable:
            return ""
        result = subprocess.run(
            [executable, "-layout", str(path), "-"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=90,
        )
        return result.stdout.decode("utf-8", errors="replace").strip() if result.returncode == 0 else ""
    if suffix in {".docx", ".pptx", ".xlsx"}:
        with contextlib.suppress(zipfile.BadZipFile, OSError):
            return extract_openxml(path)
    return ""


@dataclass
class HTTPResult:
    body: bytes
    headers: Any
    status: int
    url: str


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward an OAuth bearer token across host boundaries."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        redirected = super().redirect_request(request, file_pointer, code, message, headers, new_url)
        if redirected is None:
            return None
        old_host = urllib.parse.urlparse(request.full_url).netloc.lower()
        new_host = urllib.parse.urlparse(new_url).netloc.lower()
        if old_host != new_host:
            redirected.remove_header("Authorization")
            redirected.remove_header("authorization")
        return redirected


class SafeHTTPClient:
    def __init__(self, user_agent: str = f"CanvasBridge/{APP_VERSION}") -> None:
        self.user_agent = user_agent

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        form: dict[str, str] | None = None,
        timeout: int = HTTP_TIMEOUT_SECONDS,
    ) -> HTTPResult:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            raise RuntimeError("Refusing a non-HTTPS external request")
        request_headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        request_headers.update(headers or {})
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        opener = urllib.request.build_opener(SafeRedirectHandler())
        try:
            with opener.open(request, timeout=timeout) as response:
                return HTTPResult(response.read(), response.headers, response.status, response.url)
        except urllib.error.HTTPError as error:
            safe_body = error.read(4096).decode("utf-8", errors="replace")
            safe_body = re.sub(r'("(?:access|refresh)_token"\s*:\s*")[^"]+', r'\1[redacted]', safe_body)
            raise RuntimeError(f"Remote service returned HTTP {error.code}: {safe_body[:500]}") from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not reach the remote service: {error.reason}") from None

    def json(self, *args: Any, **kwargs: Any) -> tuple[Any, HTTPResult]:
        result = self.request(*args, **kwargs)
        try:
            return json.loads(result.body), result
        except json.JSONDecodeError:
            raise RuntimeError("Remote service returned an invalid JSON response") from None


class CanvasClient:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.http = SafeHTTPClient()

    @staticmethod
    def mobile_credentials() -> tuple[str, str, str]:
        query = urllib.parse.urlencode({"domain": urllib.parse.urlparse(CANVAS_BASE_URL).netloc, "user_agent": MOBILE_USER_AGENT})
        data, _ = SafeHTTPClient(MOBILE_USER_AGENT).json(
            f"{MOBILE_VERIFY_URL}?{query}",
            headers={"User-Agent": MOBILE_USER_AGENT},
        )
        if not data.get("authorized") or int(data.get("result", -1)) != 0:
            raise RuntimeError("UMD's canonical Canvas domain is not authorized for Canvas mobile login")
        client_id = str(data.get("client_id") or "")
        client_secret = str(data.get("client_secret") or data.get("api_key") or "")
        base_url = str(data.get("base_url") or CANVAS_BASE_URL).rstrip("/")
        if not client_id or not client_secret:
            raise RuntimeError("Canvas mobile verification did not return usable OAuth credentials")
        return client_id, client_secret, base_url

    def begin_oauth(self) -> tuple[str, str]:
        client_id, _, base_url = self.mobile_credentials()
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        now = int(time.time())
        self.db.execute("DELETE FROM pending_oauth WHERE created_at < ?", (now - OAUTH_STATE_TTL_SECONDS,))
        self.db.execute(
            "INSERT INTO pending_oauth(state_hash, created_at) VALUES(?, ?)",
            (state_hash, now),
        )
        self.db.commit()
        query = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": AUTHORIZATION_REDIRECT_URI,
                "mobile": "1",
                "purpose": "UMD_Canvas_Bridge",
                "state": state,
            }
        )
        return f"{base_url}/login/oauth2/auth?{query}", state

    def complete_oauth(self, callback_text: str) -> dict[str, Any]:
        code, state = parse_oauth_callback(callback_text)
        if not code:
            raise RuntimeError("The pasted value does not contain a Canvas authorization code")
        if not state:
            raise RuntimeError("The pasted value does not contain the OAuth state value")
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        cutoff = int(time.time()) - OAUTH_STATE_TTL_SECONDS
        row = self.db.execute(
            "SELECT state_hash FROM pending_oauth WHERE state_hash = ? AND created_at >= ?",
            (state_hash, cutoff),
        ).fetchone()
        if not row:
            raise RuntimeError("This login attempt is missing, expired, or has already been used")

        client_id, client_secret, base_url = self.mobile_credentials()
        token_data, _ = self.http.json(
            f"{base_url}/login/oauth2/token",
            method="POST",
            form={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": TOKEN_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        access_token = str(token_data.get("access_token") or "")
        refresh_token = str(token_data.get("refresh_token") or "")
        if not access_token or not refresh_token:
            raise RuntimeError("Canvas did not return both an access token and a refresh token")

        profile, _ = self._api_json_with_token(base_url, access_token, "/api/v1/users/self/profile")
        timestamp = now_iso()
        self.db.execute("DELETE FROM pending_oauth WHERE state_hash = ?", (state_hash,))
        self.db.execute(
            """
            INSERT INTO auth(
                singleton, canvas_url, access_token, refresh_token, user_json, connected_at, updated_at
            ) VALUES(1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                canvas_url = excluded.canvas_url,
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                user_json = excluded.user_json,
                connected_at = excluded.connected_at,
                updated_at = excluded.updated_at
            """,
            (base_url, access_token, refresh_token, compact_json(profile), timestamp, timestamp),
        )
        self.db.commit()
        return profile

    def auth_row(self) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM auth WHERE singleton = 1").fetchone()
        if not row:
            raise RuntimeError("Canvas is not connected; complete the private web login first")
        return row

    def refresh_access_token(self) -> str:
        row = self.auth_row()
        client_id, client_secret, base_url = self.mobile_credentials()
        token_data, _ = self.http.json(
            f"{base_url}/login/oauth2/token",
            method="POST",
            form={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": str(row["refresh_token"]),
                "redirect_uri": TOKEN_REDIRECT_URI,
                "grant_type": "refresh_token",
            },
        )
        access_token = str(token_data.get("access_token") or "")
        refresh_token = str(token_data.get("refresh_token") or row["refresh_token"])
        if not access_token:
            raise RuntimeError("Canvas token refresh did not return an access token")
        self.db.execute(
            "UPDATE auth SET access_token = ?, refresh_token = ?, updated_at = ? WHERE singleton = 1",
            (access_token, refresh_token, now_iso()),
        )
        self.db.commit()
        return access_token

    def _api_json_with_token(self, base_url: str, token: str, path_or_url: str) -> tuple[Any, HTTPResult]:
        url = path_or_url if path_or_url.startswith("https://") else f"{base_url}{path_or_url}"
        if urllib.parse.urlparse(url).netloc != urllib.parse.urlparse(base_url).netloc:
            raise RuntimeError("Refusing to send the Canvas token to another host")
        return self.http.json(url, headers={"Authorization": f"Bearer {token}"})

    def api_json(self, path_or_url: str, retry: bool = True) -> tuple[Any, HTTPResult]:
        row = self.auth_row()
        try:
            return self._api_json_with_token(str(row["canvas_url"]), str(row["access_token"]), path_or_url)
        except RuntimeError as error:
            if retry and "HTTP 401" in str(error):
                token = self.refresh_access_token()
                return self._api_json_with_token(str(row["canvas_url"]), token, path_or_url)
            raise

    def paginated(self, path: str) -> list[Any]:
        results: list[Any] = []
        next_url: str | None = path
        pages = 0
        while next_url and pages < 100:
            payload, response = self.api_json(next_url)
            if not isinstance(payload, list):
                raise RuntimeError("Canvas pagination returned a non-list response")
            results.extend(payload)
            links = parse_link_header(response.headers.get("Link", ""))
            next_url = links.get("next")
            pages += 1
        return results

    def disconnect(self) -> None:
        row = self.db.execute("SELECT canvas_url, access_token FROM auth WHERE singleton = 1").fetchone()
        if row:
            with contextlib.suppress(Exception):
                self.http.request(
                    f"{row['canvas_url']}/login/oauth2/token",
                    method="DELETE",
                    headers={"Authorization": f"Bearer {row['access_token']}"},
                )
        self.db.execute("DELETE FROM auth")
        self.db.execute("DELETE FROM pending_oauth")
        self.db.commit()


def parse_link_header(value: str) -> dict[str, str]:
    links: dict[str, str] = {}
    for part in value.split(","):
        match = re.match(r'\s*<([^>]+)>\s*;\s*rel="([^"]+)"', part)
        if match:
            links[match.group(2)] = match.group(1)
    return links


def parse_oauth_callback(value: str) -> tuple[str, str]:
    value = html.unescape(value.strip())
    if not value:
        return "", ""
    if "://" in value or value.startswith("/"):
        parsed = urllib.parse.urlparse(value)
        query = urllib.parse.parse_qs(parsed.query)
        return (query.get("code", [""])[0], query.get("state", [""])[0])
    if "code=" in value:
        query = urllib.parse.parse_qs(value.lstrip("?#"))
        return (query.get("code", [""])[0], query.get("state", [""])[0])
    return value, ""


BLOCKED_METADATA_KEYS = {
    "access_token",
    "api_key",
    "body",
    "client_secret",
    "description",
    "message",
    "preview_url",
    "refresh_token",
    "secure_params",
    "submissions_download_url",
    "syllabus_body",
    "thumbnail_url",
    "url",
    "verifier",
}


def sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_metadata(item)
            for key, item in value.items()
            if key.lower() not in BLOCKED_METADATA_KEYS
        }
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    if isinstance(value, str):
        return re.sub(
            r"([?&](?:access_token|refresh_token|token|verifier)=)[^&#\s\"']+",
            r"\1[redacted]",
            value,
            flags=re.IGNORECASE,
        )
    return value


def canvas_file_ids_from_html(value: str | None) -> set[str]:
    if not value:
        return set()
    unescaped = html.unescape(value)
    return set(re.findall(r"(?:/api/v1(?:/courses/\d+)?|/courses/\d+)?/files/(\d+)", unescaped))


def unavailable_canvas_file(error: Exception) -> bool:
    return "HTTP 404" in str(error) or "HTTP 403" in str(error)


class SyncEngine:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.canvas = CanvasClient(db)

    def run(self, course_ids: list[str] | None = None) -> dict[str, Any]:
        ensure_state_dir()
        with open(LOCK_PATH, "a+", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("A Canvas sync is already running") from None
            return self._run_locked(course_ids)

    def _run_locked(self, course_ids: list[str] | None = None) -> dict[str, Any]:
        started = now_iso()
        self.db.execute(
            """
            INSERT INTO sync_status(singleton, state, started_at, completed_at, error, summary_json)
            VALUES(1, 'running', ?, NULL, NULL, NULL)
            ON CONFLICT(singleton) DO UPDATE SET
                state = 'running', started_at = excluded.started_at,
                completed_at = NULL, error = NULL, summary_json = NULL
            """,
            (started,),
        )
        self.db.commit()
        summary = {"courses": 0, "modules": 0, "items": 0, "documents": 0, "files_downloaded": 0, "files_skipped": 0}
        try:
            if course_ids:
                courses = []
                for course_id in dict.fromkeys(str(item) for item in course_ids):
                    course, _ = self.canvas.api_json(
                        f"/api/v1/courses/{urllib.parse.quote(course_id, safe='')}"
                        "?include[]=term&include[]=syllabus_body"
                    )
                    courses.append(course)
            else:
                courses = self.canvas.paginated(
                    "/api/v1/courses?enrollment_state=active&state[]=available"
                    "&include[]=term&include[]=syllabus_body&per_page=100"
                )
                self.db.execute("UPDATE courses SET active = 0")
            for course in courses:
                course_id = str(course["id"])
                timestamp = now_iso()
                self.db.execute(
                    """
                    INSERT INTO courses(
                        id, name, course_code, term_name, start_at, end_at, active, json, synced_at
                    ) VALUES(?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name, course_code = excluded.course_code,
                        term_name = excluded.term_name, start_at = excluded.start_at,
                        end_at = excluded.end_at, active = 1, json = excluded.json,
                        synced_at = excluded.synced_at
                    """,
                    (
                        course_id,
                        str(course.get("name") or course.get("course_code") or course_id),
                        str(course.get("course_code") or ""),
                        str((course.get("term") or {}).get("name") or ""),
                        course.get("start_at"),
                        course.get("end_at"),
                        compact_json(sanitize_metadata(course)),
                        timestamp,
                    ),
                )
                syllabus = course.get("syllabus_body")
                if syllabus:
                    self._upsert_document(
                        "syllabus",
                        course_id,
                        "syllabus",
                        f"{course.get('name', 'Course')} syllabus",
                        html_to_text(str(syllabus)),
                        course.get("html_url"),
                        None,
                        course.get("updated_at"),
                        None,
                        {"source": "course.syllabus_body"},
                    )
                    summary["documents"] += 1
                course_summary = self._sync_course(course_id)
                for key, count in course_summary.items():
                    summary[key] += count
                summary["courses"] += 1
                self.db.commit()

            completed = now_iso()
            self.db.execute(
                "UPDATE sync_status SET state = 'idle', completed_at = ?, error = NULL, summary_json = ? WHERE singleton = 1",
                (completed, compact_json(summary)),
            )
            self.db.commit()
            return summary
        except Exception as error:
            self.db.execute(
                "UPDATE sync_status SET state = 'error', completed_at = ?, error = ?, summary_json = NULL WHERE singleton = 1",
                (now_iso(), str(error)[:1000]),
            )
            self.db.commit()
            raise

    def _sync_course(self, course_id: str) -> dict[str, int]:
        counts = {"modules": 0, "items": 0, "documents": 0, "files_downloaded": 0, "files_skipped": 0}
        timestamp = now_iso()
        modules = self.canvas.paginated(f"/api/v1/courses/{course_id}/modules?include[]=items&per_page=100")
        module_ids: list[str] = []
        item_ids: list[str] = []
        page_urls: set[str] = set()
        file_ids: set[str] = set()
        for module in modules:
            module_id = str(module["id"])
            module_ids.append(module_id)
            self.db.execute(
                """
                INSERT INTO modules(id, course_id, name, position, state, unlock_at, json, synced_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    course_id = excluded.course_id, name = excluded.name,
                    position = excluded.position, state = excluded.state,
                    unlock_at = excluded.unlock_at, json = excluded.json,
                    synced_at = excluded.synced_at
                """,
                (
                    module_id,
                    course_id,
                    str(module.get("name") or module_id),
                    module.get("position"),
                    module.get("state"),
                    module.get("unlock_at"),
                    compact_json(sanitize_metadata(module)),
                    timestamp,
                ),
            )
            counts["modules"] += 1
            for item in module.get("items") or []:
                item_id = str(item["id"])
                item_ids.append(item_id)
                requirement = item.get("completion_requirement")
                self.db.execute(
                    """
                    INSERT INTO module_items(
                        id, course_id, module_id, title, type, position, content_id,
                        page_url, html_url, external_url, completion_requirement, json, synced_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        course_id = excluded.course_id, module_id = excluded.module_id,
                        title = excluded.title, type = excluded.type,
                        position = excluded.position, content_id = excluded.content_id,
                        page_url = excluded.page_url, html_url = excluded.html_url,
                        external_url = excluded.external_url,
                        completion_requirement = excluded.completion_requirement,
                        json = excluded.json, synced_at = excluded.synced_at
                    """,
                    (
                        item_id,
                        course_id,
                        module_id,
                        str(item.get("title") or item_id),
                        item.get("type"),
                        item.get("position"),
                        str(item.get("content_id") or ""),
                        item.get("page_url"),
                        item.get("html_url"),
                        item.get("external_url"),
                        compact_json(requirement) if requirement else None,
                        compact_json(sanitize_metadata(item)),
                        timestamp,
                    ),
                )
                counts["items"] += 1
                if item.get("type") == "Page" and item.get("page_url"):
                    page_urls.add(str(item["page_url"]))
                if item.get("type") == "File" and item.get("content_id"):
                    file_ids.add(str(item["content_id"]))

        if module_ids:
            placeholders = ",".join("?" for _ in module_ids)
            self.db.execute(
                f"DELETE FROM modules WHERE course_id = ? AND id NOT IN ({placeholders})",
                (course_id, *module_ids),
            )
        else:
            self.db.execute("DELETE FROM modules WHERE course_id = ?", (course_id,))
        if item_ids:
            placeholders = ",".join("?" for _ in item_ids)
            self.db.execute(
                f"DELETE FROM module_items WHERE course_id = ? AND id NOT IN ({placeholders})",
                (course_id, *item_ids),
            )
        else:
            self.db.execute("DELETE FROM module_items WHERE course_id = ?", (course_id,))

        assignments = self.canvas.paginated(
            f"/api/v1/courses/{course_id}/assignments?order_by=due_at&include[]=submission&per_page=100"
        )
        assignment_ids: list[str] = []
        for assignment in assignments:
            object_id = str(assignment["id"])
            assignment_ids.append(object_id)
            file_ids.update(canvas_file_ids_from_html(assignment.get("description")))
            self._upsert_document(
                "assignment",
                course_id,
                object_id,
                str(assignment.get("name") or object_id),
                html_to_text(assignment.get("description")),
                assignment.get("html_url"),
                assignment.get("due_at"),
                assignment.get("updated_at"),
                None,
                sanitize_metadata(assignment),
            )
            counts["documents"] += 1
        self._delete_missing_documents(course_id, "assignment", assignment_ids)

        announcements = self.canvas.paginated(
            "/api/v1/announcements?"
            + urllib.parse.urlencode(
                {
                    "context_codes[]": f"course_{course_id}",
                    "start_date": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=120)).date().isoformat(),
                    "end_date": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365)).date().isoformat(),
                    "per_page": "100",
                }
            )
        )
        announcement_ids: list[str] = []
        for announcement in announcements:
            object_id = str(announcement["id"])
            announcement_ids.append(object_id)
            file_ids.update(canvas_file_ids_from_html(announcement.get("message")))
            self._upsert_document(
                "announcement",
                course_id,
                object_id,
                str(announcement.get("title") or object_id),
                html_to_text(announcement.get("message")),
                announcement.get("html_url"),
                announcement.get("posted_at"),
                announcement.get("updated_at"),
                None,
                sanitize_metadata(announcement),
            )
            counts["documents"] += 1
        self._delete_missing_documents(course_id, "announcement", announcement_ids)

        for page_url in sorted(page_urls):
            quoted = urllib.parse.quote(page_url, safe="")
            page, _ = self.canvas.api_json(f"/api/v1/courses/{course_id}/pages/{quoted}")
            file_ids.update(canvas_file_ids_from_html(page.get("body")))
            self._upsert_document(
                "page",
                course_id,
                page_url,
                str(page.get("title") or page_url),
                html_to_text(page.get("body")),
                page.get("html_url"),
                None,
                page.get("updated_at"),
                None,
                sanitize_metadata(page),
            )
            counts["documents"] += 1
        self._delete_missing_documents(course_id, "page", sorted(page_urls))

        for file_id in sorted(file_ids)[:MAX_FILES_PER_COURSE]:
            try:
                file_data, _ = self.canvas.api_json(f"/api/v1/files/{file_id}")
            except RuntimeError as error:
                if unavailable_canvas_file(error):
                    counts["files_skipped"] += 1
                    continue
                raise
            downloaded = self._sync_file(course_id, file_data)
            counts["files_downloaded" if downloaded else "files_skipped"] += 1
            counts["documents"] += 1
        self._delete_missing_documents(course_id, "file", sorted(file_ids))
        return counts

    def _delete_missing_documents(self, course_id: str, kind: str, ids: Iterable[str]) -> None:
        object_ids = [str(item) for item in ids]
        if object_ids:
            placeholders = ",".join("?" for _ in object_ids)
            self.db.execute(
                f"DELETE FROM documents WHERE course_id = ? AND kind = ? AND object_id NOT IN ({placeholders})",
                (course_id, kind, *object_ids),
            )
        else:
            self.db.execute("DELETE FROM documents WHERE course_id = ? AND kind = ?", (course_id, kind))

    def _sync_file(self, course_id: str, file_data: dict[str, Any]) -> bool:
        file_id = str(file_data["id"])
        display_name = str(file_data.get("display_name") or file_data.get("filename") or file_id)
        content_type = str(file_data.get("content-type") or file_data.get("content_type") or mimetypes.guess_type(display_name)[0] or "")
        size = int(file_data.get("size") or 0)
        eligible = (
            size <= MAX_FILE_BYTES
            and (content_type in DOWNLOADABLE_TYPES or content_type.startswith("text/"))
            and str(file_data.get("url") or "").startswith("https://")
        )
        local_path: Path | None = None
        body = ""
        downloaded = False
        if eligible:
            course_dir = FILES_DIR / safe_filename(course_id)
            course_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            local_path = course_dir / f"{safe_filename(file_id)}-{safe_filename(display_name)}"
            needs_download = not local_path.exists() or (size and local_path.stat().st_size != size)
            if needs_download:
                result = SafeHTTPClient().request(str(file_data["url"]), headers={"Accept": "*/*"}, timeout=120)
                if len(result.body) > MAX_FILE_BYTES:
                    raise RuntimeError(f"Canvas file exceeded the configured download limit: {display_name}")
                temporary = local_path.with_suffix(local_path.suffix + ".part")
                temporary.write_bytes(result.body)
                os.chmod(temporary, 0o600)
                temporary.replace(local_path)
            body = extract_file_text(local_path, content_type)
            downloaded = True
        metadata = sanitize_metadata(file_data)
        metadata.update({"content_type": content_type, "size": size, "downloaded": downloaded})
        self._upsert_document(
            "file",
            course_id,
            file_id,
            display_name,
            body,
            file_data.get("html_url"),
            None,
            file_data.get("updated_at") or file_data.get("modified_at"),
            str(local_path) if local_path else None,
            metadata,
        )
        return downloaded

    def _upsert_document(
        self,
        kind: str,
        course_id: str,
        object_id: str,
        title: str,
        body: str,
        html_url: str | None,
        due_at: str | None,
        updated_at: str | None,
        local_path: str | None,
        metadata: dict[str, Any],
    ) -> None:
        self.db.execute(
            """
            INSERT INTO documents(
                kind, course_id, object_id, title, body, html_url, due_at,
                updated_at, local_path, metadata_json, synced_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(kind, course_id, object_id) DO UPDATE SET
                title = excluded.title, body = excluded.body,
                html_url = excluded.html_url, due_at = excluded.due_at,
                updated_at = excluded.updated_at, local_path = excluded.local_path,
                metadata_json = excluded.metadata_json, synced_at = excluded.synced_at
            """,
            (
                kind,
                course_id,
                object_id,
                title,
                body,
                html_url,
                due_at,
                updated_at,
                local_path,
                compact_json(metadata),
                now_iso(),
            ),
        )


def connection_status(db: sqlite3.Connection) -> dict[str, Any]:
    auth = db.execute("SELECT user_json, connected_at, updated_at FROM auth WHERE singleton = 1").fetchone()
    sync = db.execute("SELECT * FROM sync_status WHERE singleton = 1").fetchone()
    counts = {
        "active_courses": db.execute("SELECT COUNT(*) FROM courses WHERE active = 1").fetchone()[0],
        "modules": db.execute("SELECT COUNT(*) FROM modules").fetchone()[0],
        "documents": db.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
    }
    result: dict[str, Any] = {"connected": bool(auth), "counts": counts, "public_url": PUBLIC_URL}
    if auth:
        user = json.loads(auth["user_json"])
        result.update(
            {
                "user": {"id": user.get("id"), "name": user.get("name") or user.get("short_name")},
                "connected_at": auth["connected_at"],
                "token_updated_at": auth["updated_at"],
            }
        )
    if sync:
        result["sync"] = {
            "state": sync["state"],
            "started_at": sync["started_at"],
            "completed_at": sync["completed_at"],
            "error": sync["error"],
            "summary": json.loads(sync["summary_json"]) if sync["summary_json"] else None,
        }
    return result


def list_courses(db: sqlite3.Connection, include_inactive: bool = False) -> list[dict[str, Any]]:
    where = "" if include_inactive else "WHERE active = 1"
    rows = db.execute(
        f"SELECT id, name, course_code, term_name, start_at, end_at, active, synced_at FROM courses {where} "
        "ORDER BY term_name DESC, name"
    ).fetchall()
    return [dict(row) for row in rows]


def require_course(db: sqlite3.Connection, course_id: str) -> sqlite3.Row:
    row = db.execute(
        "SELECT id, name, course_code, term_name, start_at, end_at, active, synced_at FROM courses WHERE id = ?",
        (str(course_id),),
    ).fetchone()
    if not row:
        raise RuntimeError(f"Unknown course_id: {course_id}")
    return row


def course_outline(db: sqlite3.Connection, course_id: str) -> dict[str, Any]:
    course = require_course(db, course_id)
    modules = []
    for module in db.execute(
        "SELECT id, name, position, state, unlock_at FROM modules WHERE course_id = ? ORDER BY position, id",
        (str(course_id),),
    ):
        items = [
            dict(row)
            for row in db.execute(
                """
                SELECT id, title, type, position, content_id, page_url, html_url,
                       external_url, completion_requirement
                FROM module_items WHERE module_id = ? ORDER BY position, id
                """,
                (module["id"],),
            )
        ]
        module_value = dict(module)
        module_value["items"] = items
        modules.append(module_value)
    return {"course": dict(course), "modules": modules}


def list_documents(
    db: sqlite3.Connection,
    course_id: str | None = None,
    kind: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses = []
    values: list[Any] = []
    if course_id:
        require_course(db, course_id)
        clauses.append("d.course_id = ?")
        values.append(str(course_id))
    if kind:
        clauses.append("d.kind = ?")
        values.append(kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.append(max(1, min(int(limit), 500)))
    rows = db.execute(
        f"""
        SELECT d.kind, d.course_id, c.name AS course_name, d.object_id, d.title,
               d.html_url, d.due_at, d.updated_at, d.local_path,
               substr(COALESCE(d.body, ''), 1, 1200) AS excerpt
        FROM documents d JOIN courses c ON c.id = d.course_id
        {where}
        ORDER BY CASE WHEN d.due_at IS NULL THEN 1 ELSE 0 END, d.due_at, d.title
        LIMIT ?
        """,
        values,
    ).fetchall()
    return [dict(row) for row in rows]


def get_document(db: sqlite3.Connection, course_id: str, kind: str, object_id: str) -> dict[str, Any]:
    row = db.execute(
        """
        SELECT d.*, c.name AS course_name
        FROM documents d JOIN courses c ON c.id = d.course_id
        WHERE d.course_id = ? AND d.kind = ? AND d.object_id = ?
        """,
        (str(course_id), kind, str(object_id)),
    ).fetchone()
    if not row:
        raise RuntimeError("Document not found")
    result = dict(row)
    result["metadata"] = json.loads(result.pop("metadata_json"))
    result.pop("synced_at", None)
    return result


def search_materials(db: sqlite3.Connection, query: str, course_id: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        raise RuntimeError("query must not be empty")
    if course_id:
        require_course(db, course_id)
    terms = [term.lower() for term in re.findall(r"[\w.+#-]{2,}", query)[:8]]
    if not terms:
        terms = [query.lower()]
    clauses = []
    params: list[Any] = []
    for term in terms:
        clauses.append("(lower(d.title) LIKE ? OR lower(COALESCE(d.body, '')) LIKE ?)")
        wildcard = f"%{term}%"
        params.extend([wildcard, wildcard])
    where = " AND ".join(clauses)
    if course_id:
        where = f"d.course_id = ? AND ({where})"
        params.insert(0, str(course_id))
    params.append(max(1, min(int(limit), 100)))
    rows = db.execute(
        f"""
        SELECT d.kind, d.course_id, c.name AS course_name, d.object_id, d.title,
               d.html_url, d.due_at, d.local_path,
               substr(COALESCE(d.body, ''), 1, 2000) AS excerpt
        FROM documents d JOIN courses c ON c.id = d.course_id
        WHERE {where}
        ORDER BY d.updated_at DESC, d.title
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def upcoming(db: sqlite3.Connection, days: int = 21, course_id: str | None = None) -> list[dict[str, Any]]:
    if course_id:
        require_course(db, course_id)
    start = dt.datetime.now(dt.timezone.utc)
    end = start + dt.timedelta(days=max(1, min(int(days), 180)))
    clauses = ["d.kind = 'assignment'", "d.due_at IS NOT NULL", "d.due_at >= ?", "d.due_at <= ?"]
    params: list[Any] = [start.isoformat(), end.isoformat()]
    if course_id:
        clauses.append("d.course_id = ?")
        params.append(str(course_id))
    rows = db.execute(
        f"""
        SELECT d.course_id, c.name AS course_name, d.object_id, d.title,
               d.due_at, d.html_url, substr(COALESCE(d.body, ''), 1, 800) AS excerpt
        FROM documents d JOIN courses c ON c.id = d.course_id
        WHERE {' AND '.join(clauses)}
        ORDER BY d.due_at
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


TOOLS = [
    {
        "name": "canvas_connection_status",
        "description": "Check whether UMD Canvas is connected and when the local course mirror last synchronized.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "canvas_sync",
        "description": "Synchronize UMD Canvas courses, modules, assignments, announcements, pages, and linked files into the local read-only mirror. Optionally limit the refresh to one course.",
        "inputSchema": {
            "type": "object",
            "properties": {"course_id": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "canvas_list_courses",
        "description": "List synchronized active Canvas courses and their term metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {"include_inactive": {"type": "boolean", "default": False}},
            "additionalProperties": False,
        },
    },
    {
        "name": "canvas_get_course_outline",
        "description": "Return the instructor-curated module sequence and module items for one course.",
        "inputSchema": {
            "type": "object",
            "properties": {"course_id": {"type": "string"}},
            "required": ["course_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "canvas_list_documents",
        "description": "List synchronized assignments, announcements, pages, syllabi, or files, optionally limited to one course and kind.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "string"},
                "kind": {"type": "string", "enum": ["assignment", "announcement", "page", "syllabus", "file"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "canvas_get_document",
        "description": "Get the full normalized text and metadata for one synchronized Canvas object.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "string"},
                "kind": {"type": "string", "enum": ["assignment", "announcement", "page", "syllabus", "file"]},
                "object_id": {"type": "string"},
            },
            "required": ["course_id", "kind", "object_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "canvas_search_materials",
        "description": "Search normalized course pages, assignments, announcements, syllabi, and extracted document text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "course_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "canvas_get_upcoming_assignments",
        "description": "List assignments due within a future time window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 180, "default": 21},
                "course_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
]


def execute_tool(db: sqlite3.Connection, name: str, arguments: dict[str, Any]) -> Any:
    if name == "canvas_connection_status":
        return connection_status(db)
    if name == "canvas_sync":
        course_id = arguments.get("course_id")
        return SyncEngine(db).run([str(course_id)] if course_id is not None else None)
    if name == "canvas_list_courses":
        return list_courses(db, bool(arguments.get("include_inactive", False)))
    if name == "canvas_get_course_outline":
        return course_outline(db, str(arguments["course_id"]))
    if name == "canvas_list_documents":
        return list_documents(
            db,
            str(arguments["course_id"]) if arguments.get("course_id") is not None else None,
            str(arguments["kind"]) if arguments.get("kind") is not None else None,
            int(arguments.get("limit", 100)),
        )
    if name == "canvas_get_document":
        return get_document(db, str(arguments["course_id"]), str(arguments["kind"]), str(arguments["object_id"]))
    if name == "canvas_search_materials":
        return search_materials(
            db,
            str(arguments["query"]),
            str(arguments["course_id"]) if arguments.get("course_id") is not None else None,
            int(arguments.get("limit", 25)),
        )
    if name == "canvas_get_upcoming_assignments":
        return upcoming(
            db,
            int(arguments.get("days", 21)),
            str(arguments["course_id"]) if arguments.get("course_id") is not None else None,
        )
    raise RuntimeError(f"Unknown tool: {name}")


def run_mcp() -> int:
    db = connect_db()
    for raw_line in sys.stdin:
        try:
            message = json.loads(raw_line)
            if "id" not in message:
                continue
            request_id = message["id"]
            method = message.get("method")
            params = message.get("params") or {}
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "umd-canvas-bridge", "version": APP_VERSION},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    value = execute_tool(db, str(params.get("name")), params.get("arguments") or {})
                    result = {
                        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}],
                        "structuredContent": value if isinstance(value, dict) else {"items": value},
                        "isError": False,
                    }
                except Exception as error:
                    result = {
                        "content": [{"type": "text", "text": str(error)}],
                        "isError": True,
                    }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
                print(compact_json(response), flush=True)
                continue
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as error:
            response = {
                "jsonrpc": "2.0",
                "id": message.get("id") if isinstance(locals().get("message"), dict) else None,
                "error": {"code": -32603, "message": str(error)},
            }
        print(compact_json(response), flush=True)
    return 0


PAGE_STYLE = """
:root{color-scheme:dark;--bg:#0b1020;--panel:#141b2d;--muted:#9ca8bf;--text:#f6f7fb;--accent:#e21833;--line:#29334d;--ok:#46c37b;--warn:#f3b63f}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(145deg,#080d19,#101a31);color:var(--text);font:16px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}
main{width:min(780px,calc(100% - 32px));margin:48px auto}.brand{display:flex;align-items:center;gap:12px;margin-bottom:28px}.mark{width:42px;height:42px;border-radius:12px;background:var(--accent);display:grid;place-items:center;font-weight:800}.brand h1{font-size:22px;margin:0}.brand p{margin:0;color:var(--muted);font-size:14px}
.card{background:rgba(20,27,45,.94);border:1px solid var(--line);border-radius:18px;padding:24px;margin:16px 0;box-shadow:0 18px 50px rgba(0,0,0,.22)}h2{font-size:20px;margin:0 0 10px}p{margin:8px 0}.muted{color:var(--muted)}.status{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;background:#202a43;font-size:14px}.dot{width:8px;height:8px;border-radius:50%;background:var(--warn)}.dot.ok{background:var(--ok)}
button,.button{appearance:none;border:0;border-radius:10px;background:var(--accent);color:white;font-weight:700;padding:11px 16px;cursor:pointer;text-decoration:none;display:inline-block;margin-top:10px}button.secondary,.button.secondary{background:#29334d}input,textarea{width:100%;border:1px solid #3a4665;background:#0d1425;color:white;border-radius:10px;padding:12px;font:inherit;margin:8px 0 4px}textarea{min-height:120px;resize:vertical}label{font-weight:650}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:16px}.metric{background:#0d1425;border-radius:12px;padding:14px}.metric strong{font-size:24px;display:block}.error{border-color:#733241;background:#2a1720}.success{border-color:#285c43;background:#12271d}code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em}.steps{padding-left:22px}.steps li{margin:10px 0}form.inline{display:inline}footer{color:var(--muted);font-size:13px;margin:24px 4px}
"""


def page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{html.escape(title)} · {APP_NAME}</title><style>{PAGE_STYLE}</style></head>
<body><main><div class="brand"><div class="mark">C</div><div><h1>{APP_NAME}</h1><p>Private, read-only course mirror</p></div></div>
{body}<footer>Tailnet only · UMD credentials are entered only on UMD pages · v{APP_VERSION}</footer></main></body></html>""".encode()


class WebSecurity:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.secret = get_or_create_cookie_secret(db)

    @staticmethod
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def issue_session(self) -> str:
        session = secrets.token_urlsafe(32)
        now = int(time.time())
        self.db.execute("DELETE FROM web_sessions WHERE expires_at < ?", (now,))
        self.db.execute(
            "INSERT INTO web_sessions(session_hash, created_at, expires_at) VALUES(?, ?, ?)",
            (self.digest(session), now, now + SESSION_TTL_SECONDS),
        )
        self.db.commit()
        signature = hmac.new(self.secret, session.encode(), hashlib.sha256).hexdigest()
        return f"{session}.{signature}"

    def validate_session(self, value: str | None) -> str | None:
        if not value or "." not in value:
            return None
        session, signature = value.rsplit(".", 1)
        expected = hmac.new(self.secret, session.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        row = self.db.execute(
            "SELECT expires_at FROM web_sessions WHERE session_hash = ?",
            (self.digest(session),),
        ).fetchone()
        if not row or int(row["expires_at"]) < int(time.time()):
            return None
        return session

    def csrf(self, session: str) -> str:
        return hmac.new(self.secret, f"csrf:{session}".encode(), hashlib.sha256).hexdigest()

    def verify_csrf(self, session: str, value: str) -> bool:
        return hmac.compare_digest(self.csrf(session), value)

    def create_pairing_code(self) -> str:
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = int(time.time())
        self.db.execute("DELETE FROM pairing_codes WHERE expires_at < ?", (now,))
        self.db.execute(
            "INSERT INTO pairing_codes(code_hash, created_at, expires_at) VALUES(?, ?, ?)",
            (self.digest(code), now, now + PAIRING_TTL_SECONDS),
        )
        self.db.commit()
        return code

    def consume_pairing_code(self, code: str) -> bool:
        now = int(time.time())
        digest = self.digest(re.sub(r"\D", "", code))
        row = self.db.execute(
            "SELECT code_hash FROM pairing_codes WHERE code_hash = ? AND expires_at >= ?",
            (digest, now),
        ).fetchone()
        if not row:
            return False
        self.db.execute("DELETE FROM pairing_codes WHERE code_hash = ?", (digest,))
        self.db.commit()
        return True


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "CanvasBridge"

    def log_message(self, format_string: str, *args: Any) -> None:
        safe_path = urllib.parse.urlsplit(self.path).path
        sys.stderr.write(
            f"{self.log_date_time_string()} {self.client_address[0]} "
            f"{format_string % ((safe_path,) + args[1:] if args else args)}\n"
        )

    def db(self) -> Any:
        return db_session()

    def direct_local_request(self) -> bool:
        peer = self.client_address[0]
        forwarded = self.headers.get("X-Forwarded-For")
        return peer in {"127.0.0.1", "::1"} and not forwarded

    def cookies(self) -> SimpleCookie:
        cookie = SimpleCookie()
        with contextlib.suppress(Exception):
            cookie.load(self.headers.get("Cookie", ""))
        return cookie

    def session(self, security: WebSecurity) -> str | None:
        morsel = self.cookies().get("canvas_session")
        return security.validate_session(morsel.value if morsel else None)

    def send_bytes(
        self,
        body: bytes,
        *,
        status: int = 200,
        content_type: str = "text/html; charset=utf-8",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://umd.instructure.com; base-uri 'none'; frame-ancestors 'none'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location: str, headers: dict[str, str] | None = None) -> None:
        combined = {"Location": location}
        combined.update(headers or {})
        self.send_bytes(b"", status=HTTPStatus.SEE_OTHER, headers=combined)

    def form_data(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 64 * 1024:
            raise RuntimeError("Request body is too large")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return {key: values[0] for key, values in urllib.parse.parse_qs(raw).items()}

    def require_web_session(self, db: sqlite3.Connection) -> tuple[WebSecurity, str] | None:
        security = WebSecurity(db)
        session = self.session(security)
        if session:
            return security, session
        self.send_bytes(
            page(
                "Unlock",
                """
                <section class="card"><h2>Unlock this private bridge</h2>
                <p class="muted">On the homelab, run <code>canvas-bridge pair</code>, then enter the one-time code below.</p>
                <form method="post" action="/unlock"><label for="code">Pairing code</label>
                <input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" required>
                <button type="submit">Unlock</button></form></section>
                """,
            ),
            status=HTTPStatus.UNAUTHORIZED,
        )
        return None

    def require_post_security(self, db: sqlite3.Connection, data: dict[str, str]) -> tuple[WebSecurity, str] | None:
        if self.direct_local_request():
            security = WebSecurity(db)
            return security, "local"
        authenticated = self.require_web_session(db)
        if not authenticated:
            return None
        security, session = authenticated
        if not security.verify_csrf(session, data.get("csrf", "")):
            self.send_bytes(page("Invalid request", '<section class="card error"><h2>Invalid or expired request</h2><p>Reload the page and try again.</p></section>'), status=HTTPStatus.FORBIDDEN)
            return None
        return security, session

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/healthz":
            self.send_bytes(b'{"status":"ok"}', content_type="application/json")
            return
        with self.db() as db:
            if parsed.path == "/api/status" and self.direct_local_request():
                self.send_bytes(
                    json.dumps(connection_status(db), ensure_ascii=False).encode(),
                    content_type="application/json",
                )
                return
            authenticated = self.require_web_session(db)
            if not authenticated:
                return
            security, session = authenticated
            csrf = security.csrf(session)
            if parsed.path == "/":
                self.render_home(db, csrf)
            elif parsed.path == "/auth/instructions":
                self.render_instructions(csrf)
            else:
                self.send_bytes(page("Not found", '<section class="card"><h2>Not found</h2></section>'), status=404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        with self.db() as db:
            try:
                data = self.form_data()
                if parsed.path == "/unlock":
                    security = WebSecurity(db)
                    if not security.consume_pairing_code(data.get("code", "")):
                        self.send_bytes(page("Unlock failed", '<section class="card error"><h2>Invalid or expired pairing code</h2><p>Generate a new code and try again.</p></section>'), status=HTTPStatus.UNAUTHORIZED)
                        return
                    cookie = security.issue_session()
                    self.redirect(
                        "/",
                        {
                            "Set-Cookie": f"canvas_session={cookie}; Path=/; Max-Age={SESSION_TTL_SECONDS}; Secure; HttpOnly; SameSite=Strict"
                        },
                    )
                    return
                secured = self.require_post_security(db, data)
                if not secured:
                    return
                _, _ = secured
                if parsed.path == "/auth/start":
                    auth_url, _ = CanvasClient(db).begin_oauth()
                    self.redirect(auth_url)
                elif parsed.path == "/auth/complete":
                    CanvasClient(db).complete_oauth(data.get("callback", ""))
                    start_background_sync()
                    self.redirect("/?connected=1")
                elif parsed.path == "/sync":
                    start_background_sync()
                    self.redirect("/?sync=started")
                elif parsed.path == "/disconnect":
                    CanvasClient(db).disconnect()
                    self.redirect("/?disconnected=1")
                else:
                    self.send_bytes(page("Not found", '<section class="card"><h2>Not found</h2></section>'), status=404)
            except Exception as error:
                self.send_bytes(
                    page(
                        "Request failed",
                        f'<section class="card error"><h2>Request failed</h2><p>{html.escape(str(error))}</p><a class="button secondary" href="/">Return home</a></section>',
                    ),
                    status=HTTPStatus.BAD_REQUEST,
                )

    def render_home(self, db: sqlite3.Connection, csrf: str) -> None:
        status = connection_status(db)
        if not status["connected"]:
            body = f"""
            <section class="card"><span class="status"><span class="dot"></span>Not connected</span>
            <h2 style="margin-top:14px">Connect your UMD Canvas account</h2>
            <p>You will sign in on UMD's real login page and approve Duo there. This bridge never receives your password.</p>
            <form method="post" action="/auth/start"><input type="hidden" name="csrf" value="{csrf}">
            <button type="submit">Continue to UMD login</button></form>
            <p class="muted">After authorization, Canvas will show a “Page Not Found” screen at its mobile callback. That is expected: copy the full URL, return here, and complete the connection.</p>
            <a class="button secondary" href="/auth/instructions">I already completed UMD login</a></section>
            """
        else:
            user = status.get("user") or {}
            sync = status.get("sync") or {}
            counts = status["counts"]
            sync_note = sync.get("completed_at") or "No completed sync yet"
            sync_error = f'<p class="muted">Last error: {html.escape(str(sync.get("error")))}</p>' if sync.get("error") else ""
            body = f"""
            <section class="card success"><span class="status"><span class="dot ok"></span>Connected</span>
            <h2 style="margin-top:14px">{html.escape(str(user.get("name") or "UMD Canvas"))}</h2>
            <p class="muted">Last successful sync: {html.escape(str(sync_note))}</p>{sync_error}
            <div class="grid"><div class="metric"><strong>{counts['active_courses']}</strong>active courses</div>
            <div class="metric"><strong>{counts['modules']}</strong>modules</div>
            <div class="metric"><strong>{counts['documents']}</strong>documents</div></div>
            <form method="post" action="/sync"><input type="hidden" name="csrf" value="{csrf}"><button type="submit">Sync now</button></form>
            </section>
            <section class="card"><h2>Connection controls</h2>
            <p class="muted">Disconnecting revokes the Canvas token and removes it locally. Already-synchronized course content remains until manually removed from the homelab state directory.</p>
            <form method="post" action="/disconnect"><input type="hidden" name="csrf" value="{csrf}">
            <button class="secondary" type="submit">Disconnect Canvas</button></form></section>
            """
        self.send_bytes(page("Home", body))

    def render_instructions(self, csrf: str) -> None:
        body = f"""
        <section class="card"><h2>Finish Canvas authorization</h2>
        <ol class="steps"><li>Complete the UMD login and Duo prompt.</li>
        <li>Canvas will stop on a “Page Not Found” screen at <code>sso.canvaslms.com</code>. This is the expected mobile callback.</li>
        <li>Copy the entire URL from the browser address bar.</li>
        <li>Paste it below. The one-time code is exchanged directly with Canvas and is never logged.</li></ol>
        <form method="post" action="/auth/complete"><input type="hidden" name="csrf" value="{csrf}">
        <label for="callback">Final Canvas URL</label>
        <textarea id="callback" name="callback" autocomplete="off" spellcheck="false" required></textarea>
        <button type="submit">Complete connection</button></form>
        <a class="button secondary" href="/">Cancel</a></section>
        """
        self.send_bytes(page("Finish authorization", body))


_sync_thread_lock = threading.Lock()
_sync_thread: threading.Thread | None = None


def background_sync_worker() -> None:
    try:
        with db_session() as db:
            SyncEngine(db).run()
    except Exception as error:
        print(f"Canvas background sync failed: {error}", file=sys.stderr)


def start_background_sync() -> bool:
    global _sync_thread
    with _sync_thread_lock:
        if _sync_thread and _sync_thread.is_alive():
            return False
        _sync_thread = threading.Thread(target=background_sync_worker, name="canvas-sync", daemon=True)
        _sync_thread.start()
        return True


def periodic_sync_worker(stop: threading.Event) -> None:
    while not stop.wait(max(60, SYNC_INTERVAL_SECONDS)):
        with contextlib.suppress(Exception):
            with db_session() as db:
                if db.execute("SELECT 1 FROM auth WHERE singleton = 1").fetchone():
                    start_background_sync()


def run_server() -> int:
    ensure_state_dir()
    stop = threading.Event()
    periodic = threading.Thread(target=periodic_sync_worker, args=(stop,), name="canvas-periodic-sync", daemon=True)
    periodic.start()
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), BridgeHandler)
    print(f"{APP_NAME} listening on http://{LISTEN_HOST}:{LISTEN_PORT}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return 0


def print_status() -> int:
    with db_session() as db:
        print(json.dumps(connection_status(db), ensure_ascii=False, indent=2))
    return 0


def run_pair() -> int:
    with db_session() as db:
        code = WebSecurity(db).create_pairing_code()
    print(f"Open: {PUBLIC_URL}")
    print(f"One-time pairing code: {code}")
    print("The code expires in 10 minutes and can be used once.")
    return 0


def run_sync(course_ids: list[str] | None = None) -> int:
    with db_session() as db:
        result = SyncEngine(db).run(course_ids)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_doctor() -> int:
    checks: list[tuple[str, bool, str]] = []
    try:
        ensure_state_dir()
        checks.append(("state directory", os.access(STATE_DIR, os.R_OK | os.W_OK), str(STATE_DIR)))
    except Exception as error:
        checks.append(("state directory", False, str(error)))
    try:
        _, _, base_url = CanvasClient.mobile_credentials()
        checks.append(("Canvas mobile OAuth", base_url.rstrip("/") == CANVAS_BASE_URL, base_url))
    except Exception as error:
        checks.append(("Canvas mobile OAuth", False, str(error)))
    checks.append(("PDF text extraction", bool(shutil.which("pdftotext")), shutil.which("pdftotext") or "not installed"))
    with db_session() as db:
        checks.append(("Canvas connection", bool(db.execute("SELECT 1 FROM auth WHERE singleton = 1").fetchone()), "connected" if db.execute("SELECT 1 FROM auth WHERE singleton = 1").fetchone() else "not connected yet"))
    for name, ok, detail in checks:
        print(f"{'ok' if ok else 'not ready':9} {name}: {detail}")
    required = [check for check in checks if check[0] != "Canvas connection"]
    return 0 if all(ok for _, ok, _ in required) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="run the private web service")
    subparsers.add_parser("pair", help="generate a one-time web UI pairing code")
    subparsers.add_parser("status", help="show connection and sync state")
    sync_parser = subparsers.add_parser("sync", help="run a read-only Canvas sync")
    sync_parser.add_argument(
        "--course-id",
        action="append",
        help="limit the sync to one course ID; repeat to select multiple courses",
    )
    subparsers.add_parser("doctor", help="check local state and Canvas mobile OAuth compatibility")
    subparsers.add_parser("mcp", help="run the Codex MCP server over stdio")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "serve":
        return run_server()
    if args.command == "pair":
        return run_pair()
    if args.command == "status":
        return print_status()
    if args.command == "sync":
        return run_sync(args.course_id)
    if args.command == "doctor":
        return run_doctor()
    if args.command == "mcp":
        return run_mcp()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
