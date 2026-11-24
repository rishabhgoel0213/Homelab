#!/usr/bin/env python3
"""Curated, bloat-resistant user memory shared across all Homelab agents.

Stores atomic, categorized facts plus a high-level summary in SQLite under
/srv/state/memory, renders a compact profile block into Codex, Claude Code, and
Antigravity global instruction files, exposes a CLI and tailnet web UI, and
periodically consolidates durable facts from recent T3 Code chats.
"""

import argparse
import importlib.util
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

VERSION = "1.0.0"
STATE = Path(os.environ.get("MEMORY_STATE", "/srv/state/memory"))
TIMEZONE = ZoneInfo(os.environ.get("MEMORY_TIMEZONE", "America/New_York"))
WEB = Path(os.environ.get("MEMORY_WEB", Path(__file__).resolve().parent.parent / "web"))
URL = os.environ.get("MEMORY_URL", "")
T3_DB = Path(os.environ.get("MEMORY_T3_DB", "/srv/state/t3code/userdata/statev2.sqlite"))
DEFAULT_SYNC_TARGETS = (
    "/srv/state/codex/AGENTS.md",
    "/srv/state/claude/CLAUDE.md",
    "/srv/state/antigravity/config/AGENTS.md",
)

CATEGORIES = ("identity", "preferences", "ongoing", "workflow")
CATEGORY_LABELS = {
    "identity": "Identity & Background",
    "preferences": "Preferences & Style",
    "ongoing": "Active Focus & Ongoing Context",
    "workflow": "Workflow & Tools",
}
SOURCES = ("me", "agent", "consolidator")

MAX_ACTIVE_MEMORIES = int(os.environ.get("MEMORY_MAX_ITEMS", "60"))
MAX_CONTENT_LEN = 300
MAX_SUMMARY_LEN = 1200
MAX_BODY = 256 * 1024

MARKER_START = "<!-- BEGIN USER MEMORY -->"
MARKER_END = "<!-- END USER MEMORY -->"

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{25,})\b"),
    re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{16,}|glpat-[A-Za-z0-9_-]{16,})\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|password|passwd)\s*[:=]\s*['\"]?[^\s'\"]{12,}"),
)

CONSOLIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Updated 2-4 sentence high-level bio summarizing durable facts about the user.",
        },
        "adds": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "content": {"type": "string"},
                    "expires_at": {"type": ["string", "null"]},
                    "reason": {"type": "string"},
                },
                "required": ["category", "content", "expires_at", "reason"],
                "additionalProperties": False,
            },
        },
        "updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "content": {"type": "string"},
                    "expires_at": {"type": ["string", "null"]},
                    "reason": {"type": "string"},
                },
                "required": ["id", "category", "content", "expires_at", "reason"],
                "additionalProperties": False,
            },
        },
        "deletes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "adds", "updates", "deletes"],
    "additionalProperties": False,
}

_consolidate_lock = threading.Lock()
_consolidate_running = False


class NotFound(LookupError):
    pass


# ---------------------------------------------------------------- helpers


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today_date() -> date:
    return datetime.now(TIMEZONE).date()


def parse_expires(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expires_at must be YYYY-MM-DD or null")
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError:
        raise ValueError(f"Invalid expires_at date {value!r}; use YYYY-MM-DD") from None
    return parsed.isoformat()


def check_no_secrets(text: str) -> None:
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            raise ValueError("Refusing to store text that looks like a secret or credential")


def normalize_content(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("content must be a string")
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        raise ValueError("content cannot be empty")
    if len(cleaned) > MAX_CONTENT_LEN:
        raise ValueError(f"content is too long ({len(cleaned)} > {MAX_CONTENT_LEN} chars); keep memories atomic")
    check_no_secrets(cleaned)
    return cleaned


def canonical_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def validate_category(category: str) -> str:
    if not isinstance(category, str):
        raise ValueError(f"category must be one of {', '.join(CATEGORIES)}")
    value = category.strip().lower()
    if value not in CATEGORIES:
        raise ValueError(f"Invalid category {category!r}; choose from {', '.join(CATEGORIES)}")
    return value


def validate_source(source: str) -> str:
    if source not in SOURCES:
        raise ValueError(f"Invalid source {source!r}")
    return source


def sync_target_paths() -> list[Path]:
    raw = os.environ.get("MEMORY_SYNC_TARGETS")
    if raw is None:
        return [Path(p) for p in DEFAULT_SYNC_TARGETS]
    if not raw.strip():
        return []
    return [Path(part) for part in raw.split(":") if part.strip()]


def atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".memory-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_t3_history_module():
    script = Path(os.environ.get("T3_HISTORY_SCRIPT", Path(__file__).resolve().parent / "t3-history.py"))
    spec = importlib.util.spec_from_file_location("t3_history", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load t3-history module from {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- storage


def connect(state_dir: Path | None = None) -> sqlite3.Connection:
    root = Path(state_dir or STATE)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(root / "memory.db", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=15000")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS memories(
          id TEXT PRIMARY KEY,
          category TEXT NOT NULL,
          content TEXT NOT NULL,
          pinned INTEGER NOT NULL DEFAULT 0,
          source TEXT NOT NULL,
          expires_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          last_confirmed_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS memories_cat ON memories(category, pinned DESC, updated_at DESC);

        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          batch_id TEXT NOT NULL,
          actor TEXT NOT NULL,
          action TEXT NOT NULL,
          memory_id TEXT,
          reason TEXT NOT NULL DEFAULT '',
          before_json TEXT,
          after_json TEXT,
          reverted INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS events_batch ON events(batch_id, id DESC);

        CREATE TABLE IF NOT EXISTS meta(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        INSERT OR IGNORE INTO meta(key, value) VALUES('rev', '0');
        INSERT OR IGNORE INTO meta(key, value) VALUES('summary', '');
        INSERT OR IGNORE INTO meta(key, value) VALUES('summary_updated_at', '');
        INSERT OR IGNORE INTO meta(key, value) VALUES('last_consolidated_at', '');
        INSERT OR IGNORE INTO meta(key, value) VALUES('last_consolidate_status', '{}');
        """
    )
    return db


def get_meta(db: sqlite3.Connection, key: str, default: str = "") -> str:
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))


def revision(db: sqlite3.Connection) -> int:
    return int(get_meta(db, "rev", "0"))


def bump(db: sqlite3.Connection) -> int:
    new_rev = revision(db) + 1
    set_meta(db, "rev", str(new_rev))
    return new_rev


def row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "category": row["category"],
        "content": row["content"],
        "pinned": bool(row["pinned"]),
        "source": row["source"],
        "expires_at": row["expires_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_confirmed_at": row["last_confirmed_at"],
    }


def get_memory_row(db: sqlite3.Connection, memory_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    if row is None:
        raise NotFound(f"Memory {memory_id!r} not found")
    return row


def list_memories(db: sqlite3.Connection, category: str | None = None) -> list[dict]:
    if category:
        cat = validate_category(category)
        rows = db.execute(
            "SELECT * FROM memories WHERE category=? ORDER BY pinned DESC, updated_at DESC, id ASC",
            (cat,),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM memories ORDER BY pinned DESC, updated_at DESC, id ASC").fetchall()
    order = {cat: idx for idx, cat in enumerate(CATEGORIES)}
    items = [row_to_dict(row) for row in rows]
    items.sort(key=lambda item: (order.get(item["category"], 99), not item["pinned"], item["updated_at"]))
    # Within each category keep pinned first, newest updated first.
    grouped: list[dict] = []
    for cat in CATEGORIES:
        bucket = [i for i in items if i["category"] == cat]
        bucket.sort(key=lambda i: (1 if i["pinned"] else 0, i["updated_at"]), reverse=True)
        grouped.extend(bucket)
    return grouped


def log_event(
    db: sqlite3.Connection,
    *,
    batch_id: str,
    actor: str,
    action: str,
    memory_id: str | None = None,
    reason: str = "",
    before=None,
    after=None,
) -> int:
    cur = db.execute(
        """
        INSERT INTO events(batch_id, actor, action, memory_id, reason, before_json, after_json, created_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id,
            actor,
            action,
            memory_id,
            (reason or "").strip()[:400],
            json.dumps(before, ensure_ascii=False) if before is not None else None,
            json.dumps(after, ensure_ascii=False) if after is not None else None,
            now_iso(),
        ),
    )
    return int(cur.lastrowid)


def new_id(db: sqlite3.Connection) -> str:
    for _ in range(20):
        candidate = secrets.token_hex(3)
        if not db.execute("SELECT 1 FROM memories WHERE id=?", (candidate,)).fetchone():
            return candidate
    raise RuntimeError("Could not allocate unique memory ID")


def find_duplicate(db: sqlite3.Connection, content: str, exclude_id: str | None = None) -> dict | None:
    target = canonical_key(content)
    if not target:
        return None
    for row in db.execute("SELECT * FROM memories").fetchall():
        if exclude_id and row["id"] == exclude_id:
            continue
        if canonical_key(row["content"]) == target:
            return row_to_dict(row)
    return None


def add_memory(
    db: sqlite3.Connection,
    *,
    category: str,
    content: str,
    source: str = "agent",
    pinned: bool = False,
    expires_at: str | None = None,
    reason: str = "",
    batch_id: str | None = None,
) -> dict:
    cat = validate_category(category)
    text = normalize_content(content)
    src = validate_source(source)
    exp = parse_expires(expires_at)

    dup = find_duplicate(db, text)
    if dup is not None:
        # Refresh confirmation timestamp rather than creating a duplicate entry.
        now = now_iso()
        with db:
            db.execute("UPDATE memories SET last_confirmed_at=? WHERE id=?", (now, dup["id"]))
        refreshed = row_to_dict(get_memory_row(db, dup["id"]))
        refreshed["deduplicated"] = True
        return refreshed

    count = db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    if count >= MAX_ACTIVE_MEMORIES:
        raise ValueError(
            f"Memory cap reached ({count}/{MAX_ACTIVE_MEMORIES}). "
            "Update or forget an outdated memory before adding a new one."
        )

    mem_id = new_id(db)
    now = now_iso()
    batch = batch_id or f"b-{secrets.token_hex(4)}"
    with db:
        db.execute(
            """
            INSERT INTO memories(id, category, content, pinned, source, expires_at, created_at, updated_at, last_confirmed_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (mem_id, cat, text, 1 if pinned else 0, src, exp, now, now, now),
        )
        item = row_to_dict(get_memory_row(db, mem_id))
        log_event(db, batch_id=batch, actor=src, action="add", memory_id=mem_id, reason=reason, after=item)
        bump(db)
    return item


def update_memory(
    db: sqlite3.Connection,
    memory_id: str,
    fields: dict,
    *,
    actor: str = "agent",
    reason: str = "",
    batch_id: str | None = None,
) -> dict:
    validate_source(actor)
    before = row_to_dict(get_memory_row(db, memory_id))

    cat = validate_category(fields["category"]) if "category" in fields and fields["category"] is not None else before["category"]
    text = normalize_content(fields["content"]) if "content" in fields and fields["content"] is not None else before["content"]
    pinned = bool(fields["pinned"]) if "pinned" in fields and fields["pinned"] is not None else before["pinned"]
    exp = parse_expires(fields["expires_at"]) if "expires_at" in fields else before["expires_at"]

    dup = find_duplicate(db, text, exclude_id=memory_id)
    if dup is not None:
        raise ValueError(f"Duplicate of existing memory {dup['id']}: {dup['content']!r}")

    if (
        cat == before["category"]
        and text == before["content"]
        and pinned == before["pinned"]
        and exp == before["expires_at"]
    ):
        return before

    now = now_iso()
    batch = batch_id or f"b-{secrets.token_hex(4)}"
    with db:
        db.execute(
            """
            UPDATE memories
            SET category=?, content=?, pinned=?, expires_at=?, updated_at=?, last_confirmed_at=?
            WHERE id=?
            """,
            (cat, text, 1 if pinned else 0, exp, now, now, memory_id),
        )
        after = row_to_dict(get_memory_row(db, memory_id))
        log_event(
            db,
            batch_id=batch,
            actor=actor,
            action="update",
            memory_id=memory_id,
            reason=reason,
            before=before,
            after=after,
        )
        bump(db)
    return after


def delete_memory(
    db: sqlite3.Connection,
    memory_id: str,
    *,
    actor: str = "agent",
    reason: str = "",
    allow_pinned: bool = True,
    batch_id: str | None = None,
) -> dict:
    validate_source(actor)
    before = row_to_dict(get_memory_row(db, memory_id))
    if before["pinned"] and not allow_pinned:
        raise ValueError(f"Memory {memory_id} is pinned and cannot be auto-deleted")
    batch = batch_id or f"b-{secrets.token_hex(4)}"
    with db:
        db.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        log_event(db, batch_id=batch, actor=actor, action="delete", memory_id=memory_id, reason=reason, before=before)
        bump(db)
    return before


def update_summary(
    db: sqlite3.Connection,
    summary_text: str,
    *,
    actor: str = "me",
    reason: str = "",
    batch_id: str | None = None,
) -> str:
    validate_source(actor)
    if not isinstance(summary_text, str):
        raise ValueError("summary must be a string")
    cleaned = re.sub(r"\n{3,}", "\n\n", summary_text.strip())
    if len(cleaned) > MAX_SUMMARY_LEN:
        raise ValueError(f"summary is too long ({len(cleaned)} > {MAX_SUMMARY_LEN} chars)")
    check_no_secrets(cleaned)

    before = get_meta(db, "summary", "")
    if cleaned == before:
        return cleaned
    now = now_iso()
    batch = batch_id or f"b-{secrets.token_hex(4)}"
    with db:
        set_meta(db, "summary", cleaned)
        set_meta(db, "summary_updated_at", now)
        log_event(
            db,
            batch_id=batch,
            actor=actor,
            action="summary",
            reason=reason,
            before={"summary": before},
            after={"summary": cleaned},
        )
        bump(db)
    return cleaned


def prune_expired(db: sqlite3.Connection, *, actor: str = "consolidator", batch_id: str | None = None) -> list[dict]:
    today_iso = today_date().isoformat()
    rows = db.execute(
        "SELECT * FROM memories WHERE pinned=0 AND expires_at IS NOT NULL AND expires_at < ?",
        (today_iso,),
    ).fetchall()
    removed: list[dict] = []
    if not rows:
        return removed
    batch = batch_id or f"b-{secrets.token_hex(4)}"
    with db:
        for row in rows:
            before = row_to_dict(row)
            db.execute("DELETE FROM memories WHERE id=?", (row["id"],))
            log_event(
                db,
                batch_id=batch,
                actor=actor,
                action="delete",
                memory_id=row["id"],
                reason=f"Expired ({row['expires_at']})",
                before=before,
            )
            removed.append(before)
        bump(db)
    return removed


def revert_events(db: sqlite3.Connection, *, event_id: int | None = None, batch_id: str | None = None) -> dict:
    if event_id is None and not batch_id:
        raise ValueError("Provide event_id or batch_id to revert")
    if event_id is not None:
        rows = db.execute("SELECT * FROM events WHERE id=? AND reverted=0", (event_id,)).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM events WHERE batch_id=? AND reverted=0 ORDER BY id DESC",
            (batch_id,),
        ).fetchall()
    if not rows:
        raise NotFound("No un-reverted matching events found")

    revert_batch = f"rev-{secrets.token_hex(4)}"
    reverted_ids: list[int] = []
    with db:
        for row in rows:
            action = row["action"]
            before = json.loads(row["before_json"]) if row["before_json"] else None
            after = json.loads(row["after_json"]) if row["after_json"] else None
            if action == "add" and after:
                db.execute("DELETE FROM memories WHERE id=?", (after["id"],))
            elif action == "delete" and before:
                db.execute(
                    """
                    INSERT OR REPLACE INTO memories(
                      id, category, content, pinned, source, expires_at, created_at, updated_at, last_confirmed_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        before["id"],
                        before["category"],
                        before["content"],
                        1 if before["pinned"] else 0,
                        before["source"],
                        before["expires_at"],
                        before["created_at"],
                        now_iso(),
                        before["last_confirmed_at"],
                    ),
                )
            elif action == "update" and before:
                db.execute(
                    """
                    INSERT OR REPLACE INTO memories(
                      id, category, content, pinned, source, expires_at, created_at, updated_at, last_confirmed_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        before["id"],
                        before["category"],
                        before["content"],
                        1 if before["pinned"] else 0,
                        before["source"],
                        before["expires_at"],
                        before["created_at"],
                        now_iso(),
                        before["last_confirmed_at"],
                    ),
                )
            elif action == "summary" and before is not None:
                set_meta(db, "summary", before.get("summary", ""))
                set_meta(db, "summary_updated_at", now_iso())
            db.execute("UPDATE events SET reverted=1 WHERE id=?", (row["id"],))
            reverted_ids.append(row["id"])
        log_event(
            db,
            batch_id=revert_batch,
            actor="me",
            action="revert",
            reason=f"Reverted event(s) {', '.join(str(i) for i in reverted_ids)}",
            after={"reverted_event_ids": reverted_ids},
        )
        bump(db)
    return {"reverted_event_ids": reverted_ids}


def list_events(db: sqlite3.Connection, limit: int = 40) -> list[dict]:
    rows = db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
    out: list[dict] = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "batch_id": row["batch_id"],
                "actor": row["actor"],
                "action": row["action"],
                "memory_id": row["memory_id"],
                "reason": row["reason"],
                "before": json.loads(row["before_json"]) if row["before_json"] else None,
                "after": json.loads(row["after_json"]) if row["after_json"] else None,
                "reverted": bool(row["reverted"]),
                "created_at": row["created_at"],
            }
        )
    return out


# ---------------------------------------------------------------- rendering & sync


def render_profile(db: sqlite3.Connection) -> str:
    summary = get_meta(db, "summary", "").strip()
    items = list_memories(db)
    lines = ["## User Memory"]
    if URL:
        lines.append(
            f"Curated durable facts about the user (manage at {URL} or via `memory`). "
            "Treat this as background context across all projects; do not echo it verbatim unless relevant."
        )
    else:
        lines.append(
            "Curated durable facts about the user (manage via `memory`). "
            "Treat this as background context across all projects; do not echo it verbatim unless relevant."
        )
    lines.append("")
    if summary:
        lines.append("### Overview")
        lines.append(summary)
        lines.append("")
    if items:
        for cat in CATEGORIES:
            bucket = [i for i in items if i["category"] == cat]
            if not bucket:
                continue
            lines.append(f"### {CATEGORY_LABELS[cat]}")
            for item in bucket:
                suffix_parts: list[str] = []
                if item["pinned"]:
                    suffix_parts.append("pinned")
                if item["expires_at"]:
                    suffix_parts.append(f"until {item['expires_at']}")
                suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""
                lines.append(f"- [{item['id']}] {item['content']}{suffix}")
            lines.append("")
    else:
        lines.append("_No saved user memories yet. Use `memory add` when the user shares durable preferences or asks you to remember something._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def splice_memory_block(existing_text: str, profile_markdown: str) -> str:
    block = f"{MARKER_START}\n{profile_markdown.rstrip()}\n{MARKER_END}\n"
    pattern = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END) + r"\n?", re.S)
    if pattern.search(existing_text):
        return pattern.sub(lambda _: block, existing_text, count=1)
    base = existing_text.rstrip()
    if not base:
        return block
    return base + "\n\n" + block


def sync_targets(db: sqlite3.Connection, state_dir: Path | None = None, targets: list[Path] | None = None) -> dict:
    root = Path(state_dir or STATE)
    profile_md = render_profile(db)
    profile_path = root / "profile.md"
    atomic_write(profile_path, profile_md, mode=0o600)

    synced: list[str] = []
    skipped: list[str] = []
    for target in (targets if targets is not None else sync_target_paths()):
        if not target.parent.exists():
            skipped.append(str(target))
            continue
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        updated = splice_memory_block(existing, profile_md)
        if updated != existing or not target.exists():
            atomic_write(target, updated, mode=0o600)
        synced.append(str(target))
    return {"profile": str(profile_path), "synced": synced, "skipped": skipped}


def full_state(db: sqlite3.Connection) -> dict:
    items = list_memories(db)
    try:
        last_status = json.loads(get_meta(db, "last_consolidate_status", "{}") or "{}")
    except json.JSONDecodeError:
        last_status = {}
    return {
        "version": VERSION,
        "rev": revision(db),
        "url": URL or None,
        "categories": [{"id": c, "label": CATEGORY_LABELS[c]} for c in CATEGORIES],
        "summary": get_meta(db, "summary", ""),
        "summary_updated_at": get_meta(db, "summary_updated_at", ""),
        "memories": items,
        "count": len(items),
        "max_items": MAX_ACTIVE_MEMORIES,
        "profile_markdown": render_profile(db),
        "last_consolidated_at": get_meta(db, "last_consolidated_at", ""),
        "last_consolidate_status": last_status,
        "consolidating": _consolidate_running,
        "events": list_events(db, limit=50),
    }


# ---------------------------------------------------------------- consolidation


def build_consolidate_prompt(
    *,
    summary: str,
    memories: list[dict],
    transcripts: list[dict],
    today_iso: str,
) -> str:
    mem_lines = []
    for item in memories:
        flags = []
        if item["pinned"]:
            flags.append("PINNED - DO NOT DELETE")
        if item["expires_at"]:
            flags.append(f"expires={item['expires_at']}")
        flag_str = f" ({', '.join(flags)})" if flags else ""
        mem_lines.append(f"- id={item['id']} [{item['category']}]{flag_str}: {item['content']}")
    existing_block = "\n".join(mem_lines) if mem_lines else "(none)"

    chat_blocks = []
    budget = 34000
    used = 0
    for thread in transcripts:
        header = f"=== Thread [{thread['project']}] {thread['title']} (updated {thread['updated_at']}) ==="
        lines = [header]
        for msg in thread["messages"]:
            lines.append(f"{msg['role'].upper()}: {msg['text']}")
        chunk = "\n".join(lines)
        if used + len(chunk) > budget and chat_blocks:
            break
        chat_blocks.append(chunk)
        used += len(chunk)
    chats_text = "\n\n".join(chat_blocks) if chat_blocks else "(no new chats)"

    return f"""You are maintaining a compact, ChatGPT-style personal memory profile for the user (Rishabh).
Today's date is {today_iso}.
Do NOT invoke any tools or access files. Respond ONLY with JSON matching the provided schema.

GOAL:
Keep a small, high-signal, bloat-free set of durable facts about the user (target 15-45 items, hard max {MAX_ACTIVE_MEMORIES}).

WHAT TO KEEP / ADD:
- identity: stable personal facts (university, major, background, hardware/devices, location/timezone).
- preferences: durable communication style, UI/UX tastes, coding/tooling preferences, recurring likes/dislikes.
- ongoing: active multi-week context (current semester courses, active major personal projects, upcoming travel/deadlines) — set expires_at (YYYY-MM-DD) whenever time-bounded.
- workflow: durable habits across devices/tools not already covered by generic repo docs.

WHAT TO NEVER STORE (and delete if present and unpinned):
- One-off bug fixes, temporary errors, single-session implementation details, or repo file paths/architecture.
- Temporary to-do items (those belong in the user's tasks board).
- Secrets, passwords, API keys, tokens, or raw credentials.
- Duplicates or near-duplicates of existing memories (prefer `updates` to merge/refine an existing ID).

COMPACTION RULES:
- Never include a pinned memory ID in `deletes`.
- Update existing memories in place whenever new information refines or supersedes them.
- Delete stale, completed, redundant, or low-value unpinned memories.
- Keep every `content` concise (<= 220 chars, single atomic fact).
- Rewrite `summary` as a clean, readable 2-4 sentence overview of who the user is, what they are currently focused on, and how they like agents to work with them. If there are no meaningful changes, return empty `adds`, `updates`, `deletes` and keep `summary` unchanged.

CURRENT SUMMARY:
{summary or "(empty)"}

CURRENT MEMORIES ({len(memories)}/{MAX_ACTIVE_MEMORIES}):
{existing_block}

NEW T3 CONVERSATIONS SINCE LAST CONSOLIDATION:
{chats_text}
"""


def run_llm_consolidator(prompt: str, *, backend: str = "agy", model: str | None = None, timeout: int = 180) -> dict:
    with tempfile.TemporaryDirectory(prefix="memory-consolidate-") as tmp:
        tmp_path = Path(tmp)
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(json.dumps(CONSOLIDATE_SCHEMA), encoding="utf-8")

        if backend == "agy":
            exe = shutil.which("agy")
            if not exe:
                raise RuntimeError("agy CLI not found on PATH")
            cmd = [
                exe,
                "--output-format",
                "json",
                "--disable-slash-commands",
                "--mode",
                "plan",
                "--print-timeout",
                f"{timeout}s",
                "--json-schema",
                str(schema_path),
            ]
            if model:
                cmd.extend(["--model", model])
            cmd.extend(["--print", prompt])
            proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=timeout + 30)
            if proc.returncode != 0:
                raise RuntimeError(f"agy failed (exit {proc.returncode}): {(proc.stderr or proc.stdout).strip()[:400]}")
            data = json.loads(proc.stdout)
            if isinstance(data.get("structured_output"), dict):
                return data["structured_output"]
            if isinstance(data.get("response"), str) and data["response"].strip():
                return json.loads(data["response"])
            raise RuntimeError(f"Unexpected agy response: {proc.stdout[:300]}")

        if backend == "claude":
            exe = shutil.which("claude")
            if not exe:
                raise RuntimeError("claude CLI not found on PATH")
            cmd = [
                exe,
                "-p",
                prompt,
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(CONSOLIDATE_SCHEMA),
                "--permission-mode",
                "plan",
                "--tools",
                "",
            ]
            if model:
                cmd.extend(["--model", model])
            proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=timeout + 30)
            if proc.returncode != 0:
                raise RuntimeError(f"claude failed (exit {proc.returncode}): {(proc.stderr or proc.stdout).strip()[:400]}")
            data = json.loads(proc.stdout)
            if isinstance(data.get("structured_output"), dict):
                return data["structured_output"]
            if isinstance(data.get("result"), str) and data["result"].strip():
                return json.loads(data["result"])
            raise RuntimeError(f"Unexpected claude response: {proc.stdout[:300]}")

        if backend == "codex":
            exe = shutil.which("codex")
            if not exe:
                raise RuntimeError("codex CLI not found on PATH")
            out_file = tmp_path / "out.json"
            cmd = [
                exe,
                "exec",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(out_file),
            ]
            if model:
                cmd.extend(["-m", model])
            cmd.append(prompt)
            proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, timeout=timeout + 30)
            if proc.returncode != 0:
                raise RuntimeError(f"codex failed (exit {proc.returncode}): {(proc.stderr or proc.stdout).strip()[:400]}")
            return json.loads(out_file.read_text(encoding="utf-8"))

        raise ValueError(f"Unknown consolidator backend {backend!r}")


def apply_consolidation_plan(
    db: sqlite3.Connection,
    plan: dict,
    *,
    batch_id: str | None = None,
    dry_run: bool = False,
) -> dict:
    if not isinstance(plan, dict):
        raise ValueError("Consolidation plan must be a JSON object")
    batch = batch_id or f"cons-{secrets.token_hex(4)}"
    stats = {"batch_id": batch, "added": 0, "updated": 0, "deleted": 0, "summary_changed": False, "warnings": []}

    if dry_run:
        return {
            "dry_run": True,
            "plan": plan,
            "counts": {
                "adds": len(plan.get("adds") or []),
                "updates": len(plan.get("updates") or []),
                "deletes": len(plan.get("deletes") or []),
            },
        }

    # Apply deletes first to free capacity before adds.
    for entry in plan.get("deletes") or []:
        mem_id = str(entry.get("id") or "").strip()
        reason = str(entry.get("reason") or "Pruned during consolidation")
        if not mem_id:
            continue
        try:
            delete_memory(db, mem_id, actor="consolidator", reason=reason, allow_pinned=False, batch_id=batch)
            stats["deleted"] += 1
        except (NotFound, ValueError) as exc:
            stats["warnings"].append(f"delete {mem_id}: {exc}")

    for entry in plan.get("updates") or []:
        mem_id = str(entry.get("id") or "").strip()
        reason = str(entry.get("reason") or "Consolidated update")
        if not mem_id:
            continue
        try:
            before = row_to_dict(get_memory_row(db, mem_id))
            after = update_memory(
                db,
                mem_id,
                {
                    "category": entry.get("category"),
                    "content": entry.get("content"),
                    "expires_at": entry.get("expires_at"),
                },
                actor="consolidator",
                reason=reason,
                batch_id=batch,
            )
            if after != before:
                stats["updated"] += 1
        except (NotFound, ValueError) as exc:
            stats["warnings"].append(f"update {mem_id}: {exc}")

    for entry in plan.get("adds") or []:
        reason = str(entry.get("reason") or "Extracted from recent T3 chats")
        try:
            created = add_memory(
                db,
                category=entry.get("category", ""),
                content=entry.get("content", ""),
                source="consolidator",
                expires_at=entry.get("expires_at"),
                reason=reason,
                batch_id=batch,
            )
            if not created.get("deduplicated"):
                stats["added"] += 1
        except ValueError as exc:
            stats["warnings"].append(f"add: {exc}")

    summary_val = plan.get("summary")
    if isinstance(summary_val, str) and summary_val.strip():
        before_sum = get_meta(db, "summary", "")
        try:
            after_sum = update_summary(
                db,
                summary_val,
                actor="consolidator",
                reason="Updated overview during consolidation",
                batch_id=batch,
            )
            stats["summary_changed"] = after_sum != before_sum
        except ValueError as exc:
            stats["warnings"].append(f"summary: {exc}")

    return stats


def consolidate(
    db: sqlite3.Connection,
    *,
    t3_db: Path | None = None,
    since: str | None = None,
    lookback_days: int = 14,
    limit_threads: int = 25,
    backend: str = "agy",
    model: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    runner=None,
) -> dict:
    batch = f"cons-{secrets.token_hex(4)}"
    expired = [] if dry_run else prune_expired(db, actor="consolidator", batch_id=batch)

    db_path = Path(t3_db or T3_DB)
    cursor = since or get_meta(db, "last_consolidated_at", "")
    if not cursor:
        dt = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        cursor = dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    transcripts: list[dict] = []
    if db_path.exists():
        t3_hist = load_t3_history_module()
        t3_conn = t3_hist.open_db(db_path)
        try:
            transcripts = t3_hist.recent_transcripts(
                t3_conn,
                since=cursor,
                limit=limit_threads,
                max_chars_per_thread=4500,
            )
        finally:
            t3_conn.close()

    if not transcripts and not force:
        status = {
            "ok": True,
            "ran_at": now_iso(),
            "threads_scanned": 0,
            "expired": len(expired),
            "added": 0,
            "updated": 0,
            "deleted": 0,
            "skipped": "No new T3 threads since last run",
        }
        if not dry_run:
            with db:
                set_meta(db, "last_consolidate_status", json.dumps(status, ensure_ascii=False))
                if expired:
                    bump(db)
            sync_targets(db)
        return status

    prompt = build_consolidate_prompt(
        summary=get_meta(db, "summary", ""),
        memories=list_memories(db),
        transcripts=transcripts,
        today_iso=today_date().isoformat(),
    )
    llm_fn = runner or run_llm_consolidator
    plan = llm_fn(prompt, backend=backend, model=model)
    result = apply_consolidation_plan(db, plan, batch_id=batch, dry_run=dry_run)
    if dry_run:
        result["threads_scanned"] = len(transcripts)
        return result

    newest_ts = max((t["updated_at"] for t in transcripts), default=cursor)
    status = {
        "ok": True,
        "ran_at": now_iso(),
        "batch_id": batch,
        "threads_scanned": len(transcripts),
        "expired": len(expired),
        "added": result["added"],
        "updated": result["updated"],
        "deleted": result["deleted"],
        "summary_changed": result["summary_changed"],
        "warnings": result["warnings"],
        "cursor": newest_ts,
    }
    with db:
        if newest_ts:
            set_meta(db, "last_consolidated_at", newest_ts)
        set_meta(db, "last_consolidate_status", json.dumps(status, ensure_ascii=False))
    sync_targets(db)
    return status


# ---------------------------------------------------------------- HTTP UI


def trigger_background_consolidate() -> bool:
    global _consolidate_running
    with _consolidate_lock:
        if _consolidate_running:
            return False
        _consolidate_running = True

    def worker():
        global _consolidate_running
        db = connect()
        try:
            consolidate(
                db,
                backend=os.environ.get("MEMORY_CONSOLIDATE_BACKEND", "agy"),
                model=os.environ.get("MEMORY_CONSOLIDATE_MODEL") or None,
            )
        except Exception as exc:
            err_status = {"ok": False, "ran_at": now_iso(), "error": str(exc)[:400]}
            with db:
                set_meta(db, "last_consolidate_status", json.dumps(err_status, ensure_ascii=False))
                bump(db)
        finally:
            db.close()
            with _consolidate_lock:
                _consolidate_running = False

    threading.Thread(target=worker, daemon=True).start()
    return True


class Handler(BaseHTTPRequestHandler):
    server_version = "memory/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("MEMORY_ACCESS_LOG"):
            super().log_message(fmt, *args)

    def send(self, status: int, body, content_type: str = "application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if status >= 400:
            self.close_connection = True
            self.send_header("Connection", "close")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("Request body is too large")
        if not length:
            return {}
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def same_origin(self) -> bool:
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return False
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return False
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == self.headers.get("Host")

    def handle_api(self):
        url = urlparse(self.path)
        parts = [part for part in url.path.split("/") if part]
        if self.command in ("GET", "HEAD"):
            if url.path in ("/", "/index.html"):
                return self.send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            if url.path == "/healthz":
                return self.send(200, {"ok": True, "version": VERSION})
            db = connect()
            try:
                if url.path == "/api/state":
                    return self.send(200, full_state(db))
                if url.path == "/api/rev":
                    return self.send(200, {"rev": revision(db), "consolidating": _consolidate_running})
            finally:
                db.close()
            return self.send(404, {"error": "Not found"})

        if not self.same_origin():
            return self.send(403, {"error": "Cross-site or non-JSON request refused"})
        payload = self.body()
        db = connect()
        try:
            if self.command == "POST" and parts == ["api", "memories"]:
                item = add_memory(
                    db,
                    category=payload.get("category", "preferences"),
                    content=payload.get("content", ""),
                    source="me",
                    pinned=bool(payload.get("pinned", False)),
                    expires_at=payload.get("expires_at"),
                    reason=str(payload.get("reason") or "Added in web UI"),
                )
                sync_targets(db)
                return self.send(201, item)

            if len(parts) == 3 and parts[:2] == ["api", "memories"]:
                mem_id = parts[2]
                if self.command == "PATCH":
                    item = update_memory(
                        db,
                        mem_id,
                        payload,
                        actor="me",
                        reason=str(payload.get("reason") or "Edited in web UI"),
                    )
                    sync_targets(db)
                    return self.send(200, item)
                if self.command == "DELETE":
                    removed = delete_memory(
                        db,
                        mem_id,
                        actor="me",
                        reason="Deleted in web UI",
                        allow_pinned=True,
                    )
                    sync_targets(db)
                    return self.send(200, removed)

            if self.command == "PUT" and parts == ["api", "summary"]:
                updated = update_summary(db, payload.get("summary", ""), actor="me", reason="Edited in web UI")
                sync_targets(db)
                return self.send(200, {"summary": updated})

            if self.command == "POST" and parts == ["api", "revert"]:
                res = revert_events(
                    db,
                    event_id=payload.get("event_id"),
                    batch_id=payload.get("batch_id"),
                )
                sync_targets(db)
                return self.send(200, res)

            if self.command == "POST" and parts == ["api", "consolidate"]:
                started = trigger_background_consolidate()
                return self.send(202 if started else 200, {"started": started, "running": True})
        finally:
            db.close()
        return self.send(404, {"error": "Not found"})

    def dispatch_request(self):
        try:
            self.handle_api()
        except NotFound as error:
            self.send(404, {"error": str(error)})
        except (ValueError, json.JSONDecodeError) as error:
            self.send(400, {"error": str(error)})
        except sqlite3.Error as error:
            self.send(503, {"error": f"Database error: {error}"})

    do_GET = do_HEAD = do_POST = do_PATCH = do_PUT = do_DELETE = dispatch_request


def serve(host: str, port: int) -> int:
    db = connect()
    try:
        sync_targets(db)
    finally:
        db.close()
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"memory serving on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


# ---------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory",
        description="Curated user memory shared across all server agents.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show", help="Print the rendered user memory profile")
    p_show.add_argument("--json", action="store_true")

    p_list = sub.add_parser("list", help="List saved memory items")
    p_list.add_argument("--category", choices=CATEGORIES)
    p_list.add_argument("--json", action="store_true")

    p_add = sub.add_parser("add", help="Add a concise durable memory")
    p_add.add_argument("content", nargs="+", help="Atomic fact to remember")
    p_add.add_argument("--category", "-c", choices=CATEGORIES, default="preferences")
    p_add.add_argument("--pin", action="store_true", help="Protect from auto-pruning")
    p_add.add_argument("--expires", help="Optional expiration date (YYYY-MM-DD)")
    p_add.add_argument("--source", choices=SOURCES, default="agent")
    p_add.add_argument("--reason", default="")
    p_add.add_argument("--json", action="store_true")

    p_upd = sub.add_parser("update", help="Update an existing memory by ID")
    p_upd.add_argument("id", help="Memory ID")
    p_upd.add_argument("content", nargs="*", help="New content")
    p_upd.add_argument("--category", "-c", choices=CATEGORIES)
    p_upd.add_argument("--pin", dest="pinned", action="store_true", default=None)
    p_upd.add_argument("--unpin", dest="pinned", action="store_false")
    p_upd.add_argument("--expires", dest="expires_at", help="YYYY-MM-DD or empty string to clear")
    p_upd.add_argument("--source", choices=SOURCES, default="agent")
    p_upd.add_argument("--reason", default="")
    p_upd.add_argument("--json", action="store_true")

    p_del = sub.add_parser("forget", aliases=["delete", "rm"], help="Delete a memory by ID")
    p_del.add_argument("id", help="Memory ID")
    p_del.add_argument("--source", choices=SOURCES, default="agent")
    p_del.add_argument("--reason", default="")
    p_del.add_argument("--json", action="store_true")

    p_sum = sub.add_parser("summary", help="View or set the high-level overview")
    p_sum.add_argument("text", nargs="*", help="New overview text (omit to view)")
    p_sum.add_argument("--source", choices=SOURCES, default="me")
    p_sum.add_argument("--json", action="store_true")

    p_hist = sub.add_parser("history", help="Show recent memory changes")
    p_hist.add_argument("--limit", type=int, default=25)
    p_hist.add_argument("--json", action="store_true")

    p_rev = sub.add_parser("revert", help="Undo a change event ID or consolidation batch ID")
    p_rev.add_argument("target", help="Numeric event ID or batch_id (e.g. cons-...)")
    p_rev.add_argument("--json", action="store_true")

    p_prune = sub.add_parser("prune", help="Remove expired non-pinned memories")
    p_prune.add_argument("--json", action="store_true")

    p_sync = sub.add_parser("sync", help="Render profile.md and refresh all agent instruction files")
    p_sync.add_argument("--json", action="store_true")

    p_cons = sub.add_parser("consolidate", help="Extract & compact durable memories from recent T3 chats")
    p_cons.add_argument("--since", help="Override watermark (ISO timestamp or e.g. 7d)")
    p_cons.add_argument("--lookback-days", type=int, default=14)
    p_cons.add_argument("--limit-threads", type=int, default=25)
    p_cons.add_argument("--backend", choices=("agy", "claude", "codex"), default=os.environ.get("MEMORY_CONSOLIDATE_BACKEND", "agy"))
    p_cons.add_argument("--model", default=os.environ.get("MEMORY_CONSOLIDATE_MODEL") or None)
    p_cons.add_argument("--force", action="store_true", help="Run compaction even if no new T3 threads exist")
    p_cons.add_argument("--dry-run", action="store_true", help="Print proposed plan without applying")
    p_cons.add_argument("--json", action="store_true")

    p_srv = sub.add_parser("serve", help="Run the tailnet web UI server")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8742)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "serve":
        return serve(args.host, args.port)

    db = connect()
    try:
        if args.cmd == "show":
            if args.json:
                print(json.dumps(full_state(db), ensure_ascii=False, indent=2))
            else:
                print(render_profile(db), end="")
            return 0

        if args.cmd == "list":
            items = list_memories(db, category=args.category)
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
            elif not items:
                print("No memories saved.")
            else:
                for item in items:
                    pin = " [pinned]" if item["pinned"] else ""
                    exp = f" (until {item['expires_at']})" if item["expires_at"] else ""
                    print(f"{item['id']}  [{item['category']}]  {item['content']}{pin}{exp}")
            return 0

        if args.cmd == "add":
            item = add_memory(
                db,
                category=args.category,
                content=" ".join(args.content),
                source=args.source,
                pinned=args.pin,
                expires_at=args.expires,
                reason=args.reason,
            )
            sync_targets(db)
            if args.json:
                print(json.dumps(item, ensure_ascii=False, indent=2))
            elif item.get("deduplicated"):
                print(f"Already remembered as {item['id']}: {item['content']}")
            else:
                print(f"Saved {item['id']} [{item['category']}]: {item['content']}")
            return 0

        if args.cmd == "update":
            fields: dict = {}
            if args.content:
                fields["content"] = " ".join(args.content)
            if args.category is not None:
                fields["category"] = args.category
            if args.pinned is not None:
                fields["pinned"] = args.pinned
            if args.expires_at is not None:
                fields["expires_at"] = args.expires_at or None
            if not fields:
                raise ValueError("Provide new content or at least one field flag to update")
            item = update_memory(db, args.id, fields, actor=args.source, reason=args.reason)
            sync_targets(db)
            if args.json:
                print(json.dumps(item, ensure_ascii=False, indent=2))
            else:
                print(f"Updated {item['id']} [{item['category']}]: {item['content']}")
            return 0

        if args.cmd in ("forget", "delete", "rm"):
            removed = delete_memory(db, args.id, actor=args.source, reason=args.reason, allow_pinned=True)
            sync_targets(db)
            if args.json:
                print(json.dumps(removed, ensure_ascii=False, indent=2))
            else:
                print(f"Forgot {removed['id']}: {removed['content']}")
            return 0

        if args.cmd == "summary":
            if args.text:
                updated = update_summary(db, " ".join(args.text), actor=args.source)
                sync_targets(db)
            else:
                updated = get_meta(db, "summary", "")
            if args.json:
                print(json.dumps({"summary": updated}, ensure_ascii=False, indent=2))
            else:
                print(updated or "(no overview yet)")
            return 0

        if args.cmd == "history":
            events = list_events(db, limit=args.limit)
            if args.json:
                print(json.dumps(events, ensure_ascii=False, indent=2))
            else:
                for ev in events:
                    flag = " [reverted]" if ev["reverted"] else ""
                    mem = f" {ev['memory_id']}" if ev["memory_id"] else ""
                    reason = f" — {ev['reason']}" if ev["reason"] else ""
                    print(f"#{ev['id']} ({ev['batch_id']}) {ev['created_at']} {ev['actor']} {ev['action']}{mem}{flag}{reason}")
            return 0

        if args.cmd == "revert":
            target = args.target.strip()
            if target.isdigit():
                res = revert_events(db, event_id=int(target))
            else:
                res = revert_events(db, batch_id=target)
            sync_targets(db)
            if args.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(f"Reverted event(s): {', '.join(str(i) for i in res['reverted_event_ids'])}")
            return 0

        if args.cmd == "prune":
            removed = prune_expired(db, actor="me")
            sync_targets(db)
            if args.json:
                print(json.dumps({"removed": removed}, ensure_ascii=False, indent=2))
            else:
                print(f"Pruned {len(removed)} expired memory item(s).")
            return 0

        if args.cmd == "sync":
            res = sync_targets(db)
            if args.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(f"Synced profile to {len(res['synced'])} target(s): {', '.join(res['synced']) or 'none'}")
            return 0

        if args.cmd == "consolidate":
            t3_hist = load_t3_history_module()
            since_iso = t3_hist.parse_since(args.since) if args.since else None
            res = consolidate(
                db,
                since=since_iso,
                lookback_days=args.lookback_days,
                limit_threads=args.limit_threads,
                backend=args.backend,
                model=args.model,
                force=args.force,
                dry_run=args.dry_run,
            )
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0
    except (NotFound, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
