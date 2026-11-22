#!/usr/bin/env python3
"""Fast Jev-backed tab space router for Zen Browser."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import signal
import sys
import threading
import time
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

DEFAULT_JEV_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_JEV_MODEL = "jev-latest"
DEFAULT_MIN_CONFIDENCE = 0.65
DEFAULT_MIN_SHOULD_MOVE = 0.65
DEFAULT_HOST_CACHE_TTL = 6 * 3600
DEFAULT_PAGE_CACHE_TTL = 15 * 60
DEFAULT_MAX_CACHE_ENTRIES = 2048

DEFAULT_SPACE_CRITERIA: dict[str, str] = {
    "Default": (
        "General everyday browsing, personal email, news, entertainment, shopping, "
        "social media, travel, sports, casual videos, general web searches, or "
        "anything that does not strongly belong in a specialized Space."
    ),
    "School": (
        "University coursework, UMD / Maryland / CMSC classes, Canvas, ELMS, Piazza, "
        "Gradescope, Overleaf, university portals, lectures, textbooks, assignments, "
        "academic papers, study resources, and student administration."
    ),
    "Server": (
        "Homelab infrastructure, NixOS, Nix, Linux administration, self-hosted "
        "internal.therealrishabh.com services, Tailscale, Cloudflare, Docker, Caddy, "
        "GitHub repositories, programming documentation, cloud/DevOps, and software "
        "engineering work."
    ),
    "Finances": (
        "Banking, credit cards, brokerage, investing, retirement accounts, taxes, "
        "budgeting, bills, insurance, payroll, financial statements, and personal "
        "finance tools."
    ),
    "Apps": (
        "Standalone interactive web applications, productivity suites, messaging "
        "and communication web apps, calendars, notes, task boards, design tools, "
        "and daily-driver SaaS utilities."
    ),
}

MULTI_TOPIC_HOSTS: frozenset[str] = frozenset(
    {
        "youtube.com",
        "youtu.be",
        "m.youtube.com",
        "docs.google.com",
        "drive.google.com",
        "sheets.google.com",
        "slides.google.com",
        "github.com",
        "gitlab.com",
        "reddit.com",
        "old.reddit.com",
        "notion.so",
        "chatgpt.com",
        "claude.ai",
        "gemini.google.com",
        "google.com",
        "bing.com",
        "duckduckgo.com",
        "wikipedia.org",
        "en.wikipedia.org",
        "arxiv.org",
        "medium.com",
        "substack.com",
        "x.com",
        "twitter.com",
        "linkedin.com",
        "localhost",
        "127.0.0.1",
    }
)

TRANSIENT_HOST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|\.)duosecurity\.com$", re.IGNORECASE),
    re.compile(r"(^|\.)auth0\.com$", re.IGNORECASE),
    re.compile(r"(^|\.)okta\.com$", re.IGNORECASE),
    re.compile(r"(^|\.)login\.microsoftonline\.com$", re.IGNORECASE),
    re.compile(r"(^|\.)login\.live\.com$", re.IGNORECASE),
    re.compile(r"(^|\.)shib\.idm\.umd\.edu$", re.IGNORECASE),
    re.compile(r"(^|\.)sso\.", re.IGNORECASE),
    re.compile(r"(^|\.)idp\.", re.IGNORECASE),
    re.compile(r"(^|\.)checkout\.stripe\.com$", re.IGNORECASE),
)

TRANSIENT_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/o/oauth2(/|$)", re.IGNORECASE),
    re.compile(r"/oauth2?(/|$)", re.IGNORECASE),
    re.compile(r"/saml2?(/|$)", re.IGNORECASE),
    re.compile(r"/openid(/|$)", re.IGNORECASE),
    re.compile(r"/authorize(/|$)", re.IGNORECASE),
    re.compile(r"/signin/v2/", re.IGNORECASE),
    re.compile(r"/ServiceLogin", re.IGNORECASE),
)

LOG = logging.getLogger("zen-space-router")


def normalize_host(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def is_multi_topic_host(host: str) -> bool:
    norm = normalize_host(host)
    if norm in MULTI_TOPIC_HOSTS:
        return True
    if norm.endswith(".internal.therealrishabh.com"):
        return False
    return any(norm.endswith("." + item) for item in MULTI_TOPIC_HOSTS)


def classify_non_routable(url: str) -> str | None:
    if not url or not isinstance(url, str):
        return "empty_url"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "non_http_scheme"
    host = normalize_host(parsed.hostname or "")
    if not host:
        return "missing_host"
    if host == "accounts.google.com" and any(
        p.search(parsed.path or "") for p in TRANSIENT_PATH_PATTERNS
    ):
        return "transient_auth"
    if any(p.search(host) for p in TRANSIENT_HOST_PATTERNS):
        return "transient_auth"
    if any(p.search(parsed.path or "") for p in TRANSIENT_PATH_PATTERNS):
        return "transient_auth"
    return None


def build_cache_key(
    url: str,
    title: str,
    spaces: list[dict[str, str]],
    criteria: dict[str, str],
) -> tuple[str, bool]:
    parsed = urlparse(url)
    host = normalize_host(parsed.hostname or "")
    multi = is_multi_topic_host(host)
    space_sig = "|".join(f"{s['name']}={criteria.get(s['name'], '')}" for s in spaces)
    sig_hash = hashlib.sha256(space_sig.encode("utf-8")).hexdigest()[:12]

    if not multi:
        return f"host:{host}:{sig_hash}", False

    path = (parsed.path or "/").rstrip("/") or "/"
    query_part = ""
    if host in ("youtube.com", "m.youtube.com"):
        vid = parse_qs(parsed.query).get("v", [""])[0]
        if vid:
            query_part = f"?v={vid}"
    elif host in ("google.com", "bing.com", "duckduckgo.com"):
        q = parse_qs(parsed.query).get("q", [""])[0]
        if q:
            query_part = f"?q={q[:120]}"

    title_norm = " ".join((title or "").strip().lower().split())[:160]
    page_raw = f"{host}{path}{query_part}|{title_norm}"
    page_hash = hashlib.sha256(page_raw.encode("utf-8")).hexdigest()[:16]
    return f"page:{host}:{page_hash}:{sig_hash}", True


def build_space_criteria(
    spaces: list[dict[str, str]],
    custom_criteria: dict[str, str] | None,
) -> dict[str, str]:
    custom = custom_criteria if isinstance(custom_criteria, dict) else {}
    criteria: dict[str, str] = {}
    for space in spaces:
        name = space["name"]
        custom_desc = custom.get(name)
        if isinstance(custom_desc, str) and custom_desc.strip():
            criteria[name] = custom_desc.strip()
        elif name in DEFAULT_SPACE_CRITERIA:
            criteria[name] = DEFAULT_SPACE_CRITERIA[name]
        else:
            criteria[name] = f"Tabs and websites directly related to '{name}'."
    return criteria


class TTLCache:
    """Thread-safe bounded LRU + TTL cache."""

    def __init__(self, max_entries: int = DEFAULT_MAX_CACHE_ENTRIES) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._lock:
            item = self._entries.get(key)
            if item is None:
                return None
            expires_at, value = item
            if now >= expires_at:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return dict(value)

    def set(self, key: str, value: dict[str, Any], ttl_seconds: float) -> None:
        expires_at = time.monotonic() + ttl_seconds
        with self._lock:
            self._entries[key] = (expires_at, dict(value))
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


class JevRouter:
    """Evaluates tab metadata against Zen Spaces using TypeSafe AI Jev."""

    def __init__(
        self,
        api_key: str,
        *,
        jev_url: str = DEFAULT_JEV_URL,
        model: str = DEFAULT_JEV_MODEL,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        min_should_move: float = DEFAULT_MIN_SHOULD_MOVE,
        timeout_seconds: float = 2.0,
        host_cache_ttl: float = DEFAULT_HOST_CACHE_TTL,
        page_cache_ttl: float = DEFAULT_PAGE_CACHE_TTL,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.jev_url = jev_url
        self.model = model
        self.min_confidence = min_confidence
        self.min_should_move = min_should_move
        self.host_cache_ttl = host_cache_ttl
        self.page_cache_ttl = page_cache_ttl
        self.cache = TTLCache()
        if http_client is not None:
            self._client = http_client
            self._owns_client = False
        else:
            self._client = httpx.Client(
                http2=True,
                timeout=httpx.Timeout(timeout_seconds, connect=1.0),
                limits=httpx.Limits(max_keepalive_connections=8, max_connections=16),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            self._owns_client = True

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def route(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()

        url = str(payload.get("url") or "").strip()
        title = str(payload.get("title") or "").strip()
        opener_url = str(payload.get("openerUrl") or "").strip()
        current_space_id = str(payload.get("currentSpaceId") or "").strip()
        current_space_name = str(payload.get("currentSpaceName") or "").strip()
        raw_spaces = payload.get("spaces")
        custom_criteria = payload.get("customCriteria")
        bypass_cache = bool(payload.get("bypassCache", False))

        skip_reason = classify_non_routable(url)
        if skip_reason is not None:
            return self._stay_result(
                reason=skip_reason,
                source="rules",
                started=started,
            )

        spaces = self._normalize_spaces(raw_spaces)
        if len(spaces) < 2:
            return self._stay_result(
                reason="insufficient_spaces",
                source="rules",
                started=started,
            )

        by_name = {space["name"]: space["uuid"] for space in spaces}
        if not current_space_name and current_space_id:
            for space in spaces:
                if space["uuid"] == current_space_id:
                    current_space_name = space["name"]
                    break

        criteria = build_space_criteria(spaces, custom_criteria)
        cache_key, is_page_key = build_cache_key(url, title, spaces, criteria)

        cached = None if bypass_cache else self.cache.get(cache_key)
        if cached is not None:
            return self._finalize_decision(
                decision=cached,
                by_name=by_name,
                current_space_id=current_space_id,
                current_space_name=current_space_name,
                source="cache",
                started=started,
                payload=payload,
            )

        jev_body = self._build_jev_request(
            url=url,
            title=title,
            opener_url=opener_url,
            current_space_name=current_space_name,
            criteria=criteria,
        )

        try:
            response = self._client.post(self.jev_url, json=jev_body)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            LOG.warning("Jev request failed: %s", type(exc).__name__)
            return self._stay_result(
                reason="upstream_error",
                source="error",
                started=started,
                error=type(exc).__name__,
            )

        parsed_decision = self._parse_jev_response(data)
        if parsed_decision is None:
            return self._stay_result(
                reason="invalid_upstream_response",
                source="error",
                started=started,
            )

        ttl = self.page_cache_ttl if is_page_key else self.host_cache_ttl
        self.cache.set(cache_key, parsed_decision, ttl_seconds=ttl)

        return self._finalize_decision(
            decision=parsed_decision,
            by_name=by_name,
            current_space_id=current_space_id,
            current_space_name=current_space_name,
            source="jev",
            started=started,
            payload=payload,
        )

    @staticmethod
    def _normalize_spaces(raw_spaces: Any) -> list[dict[str, str]]:
        if not isinstance(raw_spaces, list):
            return []
        result: list[dict[str, str]] = []
        seen_names: set[str] = set()
        for item in raw_spaces:
            if not isinstance(item, dict):
                continue
            uuid = str(item.get("uuid") or "").strip()
            name = str(item.get("name") or "").strip()
            if not uuid or not name or name in seen_names:
                continue
            seen_names.add(name)
            result.append({"uuid": uuid, "name": name})
        return result

    def _build_jev_request(
        self,
        *,
        url: str,
        title: str,
        opener_url: str,
        current_space_name: str,
        criteria: dict[str, str],
    ) -> dict[str, Any]:
        parsed = urlparse(url)
        state: dict[str, Any] = {
            "url": url[:512],
            "host": normalize_host(parsed.hostname or ""),
            "path": (parsed.path or "/")[:256],
            "title": title[:256],
        }
        if opener_url:
            opener_parsed = urlparse(opener_url)
            state["opener_host"] = normalize_host(opener_parsed.hostname or "")
            state["opener_url"] = opener_url[:256]
        if current_space_name:
            state["current_space"] = current_space_name

        return {
            "model": self.model,
            "state": state,
            "questions": {
                "target_space": {
                    "type": "choice",
                    "instructions": (
                        "Which browser Space best organizes this newly opened tab "
                        "based on its URL, host, path, and page title?"
                    ),
                    "criteria": criteria,
                },
                "should_move": {
                    "type": "noul",
                    "instructions": (
                        "Is this a substantive destination page that clearly belongs "
                        "to a specific Space rather than a transient/auth/helper page?"
                    ),
                    "criteria": {
                        "true": (
                            "A real webpage, app, document, video, repo, or portal "
                            "whose topic clearly identifies which Space it belongs in."
                        ),
                        "false": (
                            "A login/SSO/2FA/OAuth page, payment/checkout popup, "
                            "blank or loading stub, or completely ambiguous page."
                        ),
                    },
                },
            },
        }

    @staticmethod
    def _parse_jev_response(data: Any) -> dict[str, Any] | None:
        if not isinstance(data, dict):
            return None
        answers = data.get("answers")
        if not isinstance(answers, dict):
            return None
        target = answers.get("target_space")
        should_move_ans = answers.get("should_move")
        if not isinstance(target, dict) or not isinstance(should_move_ans, dict):
            return None

        choice = target.get("choice")
        if not isinstance(choice, str) or not choice.strip():
            return None

        probabilities = target.get("probabilities")
        if not isinstance(probabilities, dict):
            probabilities = {}

        confidence = target.get("confidence")
        if not isinstance(confidence, (int, float)):
            prob = probabilities.get(choice, 0.0)
            confidence = float(prob) if isinstance(prob, (int, float)) else 0.0

        should_move = should_move_ans.get("noul")
        if not isinstance(should_move, (int, float)):
            should_move = 0.0

        return {
            "choice": choice.strip(),
            "confidence": float(confidence),
            "shouldMove": float(should_move),
            "probabilities": {
                str(k): round(float(v), 4)
                for k, v in probabilities.items()
                if isinstance(v, (int, float))
            },
            "model": str(data.get("model") or DEFAULT_JEV_MODEL),
        }

    def _finalize_decision(
        self,
        *,
        decision: dict[str, Any],
        by_name: dict[str, str],
        current_space_id: str,
        current_space_name: str,
        source: str,
        started: float,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        choice = decision["choice"]
        confidence = decision["confidence"]
        should_move = decision["shouldMove"]
        target_space_id = by_name.get(choice)

        min_confidence = payload.get("minConfidence", self.min_confidence)
        min_should_move = payload.get("minShouldMove", self.min_should_move)
        if not isinstance(min_confidence, (int, float)):
            min_confidence = self.min_confidence
        if not isinstance(min_should_move, (int, float)):
            min_should_move = self.min_should_move

        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)

        action = "stay"
        reason = "matched"
        if not target_space_id:
            reason = "unknown_space"
        elif target_space_id == current_space_id or choice == current_space_name:
            reason = "already_in_space"
        elif should_move < float(min_should_move):
            reason = "low_should_move"
        elif confidence < float(min_confidence):
            reason = "low_confidence"
        else:
            action = "move"
            reason = "routed"

        return {
            "action": action,
            "reason": reason,
            "source": source,
            "targetSpaceId": target_space_id,
            "targetSpaceName": choice,
            "confidence": round(confidence, 4),
            "shouldMove": round(should_move, 4),
            "probabilities": decision["probabilities"],
            "model": decision["model"],
            "latencyMs": latency_ms,
        }

    @staticmethod
    def _stay_result(
        *,
        reason: str,
        source: str,
        started: float,
        error: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "action": "stay",
            "reason": reason,
            "source": source,
            "targetSpaceId": None,
            "targetSpaceName": None,
            "confidence": 0.0,
            "shouldMove": 0.0,
            "probabilities": {},
            "latencyMs": round((time.perf_counter() - started) * 1000.0, 1),
        }
        if error:
            result["error"] = error
        return result


def make_handler(router: JevRouter) -> type[BaseHTTPRequestHandler]:
    class RouterHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            LOG.info("%s - " + format, self.address_string(), *args)

        def _send_json(self, status: int, body: dict[str, Any]) -> None:
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "model": router.model,
                        "cacheEntries": len(router.cache),
                        "defaultCriteria": DEFAULT_SPACE_CRITERIA,
                    },
                )
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_DELETE(self) -> None:
            if self.path == "/cache":
                cleared = router.cache.clear()
                self._send_json(HTTPStatus.OK, {"ok": True, "cleared": cleared})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:
            if self.path == "/cache/clear":
                cleared = router.cache.clear()
                self._send_json(HTTPStatus.OK, {"ok": True, "cleared": cleared})
                return

            if self.path != "/route":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return

            content_length = int(self.headers.get("Content-Length") or "0")
            if content_length <= 0 or content_length > 65536:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_content_length"},
                )
                return

            try:
                raw = self.rfile.read(content_length)
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                return

            if not isinstance(payload, dict):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "expected_object"})
                return

            result = router.route(payload)
            self._send_json(HTTPStatus.OK, result)

    return RouterHandler


def load_api_key(key_file: Path | None) -> str:
    if key_file is not None:
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key
    env_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if env_key:
        return env_key
    raise RuntimeError("Missing Jev API key (--api-key-file or TYPESAFE_API_KEY).")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Zen Space Router backed by Jev.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8129)
    parser.add_argument("--api-key-file", type=Path, default=None)
    parser.add_argument("--jev-url", default=DEFAULT_JEV_URL)
    parser.add_argument("--model", default=DEFAULT_JEV_MODEL)
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument(
        "--min-should-move", type=float, default=DEFAULT_MIN_SHOULD_MOVE
    )
    parser.add_argument("--timeout", type=float, default=2.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args(argv)
    api_key = load_api_key(args.api_key_file)
    router = JevRouter(
        api_key=api_key,
        jev_url=args.jev_url,
        model=args.model,
        min_confidence=args.min_confidence,
        min_should_move=args.min_should_move,
        timeout_seconds=args.timeout,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(router))

    def _shutdown(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    LOG.info(
        "Listening on http://%s:%d (model=%s)",
        args.host,
        args.port,
        args.model,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        router.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
