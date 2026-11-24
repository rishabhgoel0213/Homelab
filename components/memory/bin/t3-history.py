#!/usr/bin/env python3
"""Read-only search and transcript reader for T3 Code's SQLite chat history."""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "1.0.0"
DEFAULT_DB = Path(os.environ.get("T3_HISTORY_DB", "/srv/state/t3code/userdata/statev2.sqlite"))
DEFAULT_URL = os.environ.get("T3_HISTORY_URL", "https://t3code.internal.therealrishabh.com").rstrip("/")
TIMEZONE = ZoneInfo(os.environ.get("T3_HISTORY_TIMEZONE", "America/New_York"))

ATTACHMENT_ONLY_PLACEHOLDER = (
    "[User attached one or more files without additional text. "
    "Respond using the conversation context and the attached files.]"
)


class NotFound(LookupError):
    pass


def open_db(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DEFAULT_DB)
    if not path.exists():
        raise FileNotFoundError(f"T3 SQLite database not found at {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def parse_since(value: str | None) -> str | None:
    """Parse an ISO timestamp, YYYY-MM-DD date, or relative duration (e.g. 7d, 24h) into UTC ISO."""
    if not value:
        return None
    raw = value.strip()
    match = re.fullmatch(r"(\d+)\s*([dhmw])", raw.lower())
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        delta = {
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
            "w": timedelta(weeks=amount),
        }[unit]
        dt = datetime.now(timezone.utc) - delta
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        dt = datetime.fromisoformat(raw).replace(tzinfo=TIMEZONE).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Invalid --since value {value!r}; use e.g. '7d', '24h', or YYYY-MM-DD") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TIMEZONE)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def format_local(iso_ts: str | None) -> str:
    if not iso_ts:
        return ""
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).astimezone(TIMEZONE)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso_ts


def thread_url(thread_id: str) -> str:
    return f"{DEFAULT_URL}/{thread_id}" if DEFAULT_URL else thread_id


def normalize_query(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u2018", "'").strip()


def extract_terms(query: str) -> list[str]:
    cleaned = normalize_query(query)
    # Preserve quoted phrases as single tokens, split remaining words.
    tokens: list[str] = []
    for match in re.finditer(r'"([^"]+)"|(\S+)', cleaned):
        tok = (match.group(1) or match.group(2) or "").strip()
        if tok:
            tokens.append(tok)
    return tokens


def build_snippet(text: str, terms: list[str], max_len: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if not compact:
        return ""
    if len(compact) <= max_len:
        return compact
    low = compact.lower()
    pos = -1
    for term in terms:
        idx = low.find(term.lower())
        if idx != -1 and (pos == -1 or idx < pos):
            pos = idx
    if pos == -1:
        return compact[: max_len - 1].rstrip() + "…"
    start = max(0, pos - max_len // 3)
    end = min(len(compact), start + max_len)
    if end - start < max_len:
        start = max(0, end - max_len)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(compact) else ""
    return prefix + compact[start:end].strip() + suffix


def clean_message_text(text: str | None) -> str:
    if not text:
        return ""
    value = text.strip()
    if value.lower().startswith("ultrathink:"):
        value = value[len("ultrathink:") :].lstrip()
    if value == ATTACHMENT_ONLY_PLACEHOLDER:
        return ""
    return value


def project_filter_sql(project: str | None, params: list) -> str:
    if not project:
        return ""
    params.extend([project, f"%{project}%", f"%{project}%"])
    return " AND (t.project_id = ? OR lower(COALESCE(p.title, '')) LIKE lower(?) OR lower(COALESCE(p.workspace_root, '')) LIKE lower(?))"


def list_projects(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
          p.project_id,
          p.title,
          p.workspace_root,
          p.archived_at,
          COUNT(CASE WHEN t.deleted_at IS NULL
                      AND COALESCE(json_extract(t.payload_json, '$.lineage.relationshipToParent'), '') != 'subagent'
                     THEN 1 END) AS thread_count,
          MAX(CASE WHEN t.deleted_at IS NULL THEN t.updated_at END) AS last_thread_at
        FROM projection_projects p
        LEFT JOIN orchestration_v2_projection_threads t ON t.project_id = p.project_id
        WHERE p.deleted_at IS NULL
        GROUP BY p.project_id
        ORDER BY COALESCE(last_thread_at, p.updated_at) DESC
        """
    ).fetchall()
    return [
        {
            "project_id": row["project_id"],
            "title": row["title"],
            "workspace_root": row["workspace_root"],
            "archived": row["archived_at"] is not None,
            "thread_count": row["thread_count"],
            "last_thread_at": row["last_thread_at"],
        }
        for row in rows
    ]


def list_threads(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
    active_only: bool = False,
    include_subagents: bool = False,
    since: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    since_iso = parse_since(since)
    params: list = []
    where = ["t.deleted_at IS NULL"]
    if active_only:
        where.append("t.archived_at IS NULL")
    if not include_subagents:
        where.append("COALESCE(json_extract(t.payload_json, '$.lineage.relationshipToParent'), '') != 'subagent'")
    if since_iso:
        where.append("t.updated_at >= ?")
        params.append(since_iso)
    proj_clause = project_filter_sql(project, params)
    sql = f"""
        SELECT
          t.thread_id,
          t.project_id,
          COALESCE(p.title, '') AS project_title,
          t.title,
          t.default_provider,
          t.created_at,
          t.updated_at,
          t.archived_at,
          (
            SELECT COUNT(*)
            FROM orchestration_v2_projection_messages m
            WHERE m.thread_id = t.thread_id
              AND m.streaming = 0
              AND (m.role = 'assistant' OR (m.role = 'user' AND COALESCE(json_extract(m.payload_json, '$.createdBy'), 'user') = 'user'))
          ) AS message_count
        FROM orchestration_v2_projection_threads t
        LEFT JOIN projection_projects p ON p.project_id = t.project_id
        WHERE {' AND '.join(where)} {proj_clause}
        ORDER BY t.updated_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([max(1, min(limit, 200)), max(0, offset)])
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "thread_id": row["thread_id"],
            "project_id": row["project_id"],
            "project": row["project_title"],
            "title": row["title"],
            "provider": row["default_provider"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "archived": row["archived_at"] is not None,
            "message_count": row["message_count"],
            "url": thread_url(row["thread_id"]),
        }
        for row in rows
    ]


def has_fts_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='orchestration_v2_message_search'"
    ).fetchone()
    return row is not None


def search_threads(
    conn: sqlite3.Connection,
    query: str,
    *,
    project: str | None = None,
    active_only: bool = False,
    include_subagents: bool = False,
    since: str | None = None,
    limit: int = 10,
) -> list[dict]:
    terms = extract_terms(query)
    if not terms:
        raise ValueError("Search query cannot be empty")
    since_iso = parse_since(since)
    limit = max(1, min(limit, 100))

    common_where = ["t.deleted_at IS NULL"]
    common_params: list = []
    if active_only:
        common_where.append("t.archived_at IS NULL")
    if not include_subagents:
        common_where.append(
            "COALESCE(json_extract(t.payload_json, '$.lineage.relationshipToParent'), '') != 'subagent'"
        )
    if since_iso:
        common_where.append("t.updated_at >= ?")
        common_params.append(since_iso)
    proj_clause = project_filter_sql(project, common_params)
    thread_filter = f"{' AND '.join(common_where)} {proj_clause}"

    results: dict[str, dict] = {}

    def record_hit(row, snippet: str, score: float, match_in: str, matched_at: str | None = None):
        tid = row["thread_id"]
        entry = results.get(tid)
        if entry is None:
            entry = {
                "thread_id": tid,
                "project_id": row["project_id"],
                "project": row["project_title"],
                "title": row["title"],
                "provider": row["default_provider"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "archived": row["archived_at"] is not None,
                "url": thread_url(tid),
                "score": 0.0,
                "match_count": 0,
                "matches": [],
            }
            results[tid] = entry
        entry["score"] += score
        entry["match_count"] += 1
        if snippet and len(entry["matches"]) < 3:
            entry["matches"].append(
                {
                    "where": match_in,
                    "created_at": matched_at or row["updated_at"],
                    "snippet": snippet,
                }
            )

    # 1. Match thread titles and project names directly.
    title_clauses = " AND ".join(
        "(lower(t.title) LIKE lower(?) OR lower(COALESCE(p.title, '')) LIKE lower(?))" for _ in terms
    )
    title_params: list = []
    for term in terms:
        pat = f"%{term}%"
        title_params.extend([pat, pat])
    title_rows = conn.execute(
        f"""
        SELECT
          t.thread_id, t.project_id, COALESCE(p.title, '') AS project_title,
          t.title, t.default_provider, t.created_at, t.updated_at, t.archived_at
        FROM orchestration_v2_projection_threads t
        LEFT JOIN projection_projects p ON p.project_id = t.project_id
        WHERE {thread_filter} AND ({title_clauses})
        ORDER BY t.updated_at DESC
        LIMIT ?
        """,
        common_params + title_params + [limit * 3],
    ).fetchall()
    for row in title_rows:
        record_hit(row, f"Title: {row['title']}", 3.0, "title", row["updated_at"])

    # 2. Match message text via FTS5 trigram index when possible, with LIKE filter for short terms.
    trigram_terms = [t for t in terms if len(t) >= 3]
    short_terms = [t for t in terms if len(t) < 3]

    if trigram_terms and has_fts_table(conn):
        fts_expr = " ".join('"' + t.replace('"', '""') + '"' for t in trigram_terms)
        extra_like = ""
        extra_params: list = []
        if short_terms:
            extra_like = " AND " + " AND ".join(
                "lower(COALESCE(json_extract(m.payload_json, '$.text'), '')) LIKE lower(?)" for _ in short_terms
            )
            extra_params = [f"%{t}%" for t in short_terms]
        msg_rows = conn.execute(
            f"""
            SELECT
              t.thread_id, t.project_id, COALESCE(p.title, '') AS project_title,
              t.title, t.default_provider, t.created_at, t.updated_at, t.archived_at,
              m.role, m.created_at AS msg_created_at,
              json_extract(m.payload_json, '$.text') AS msg_text
            FROM orchestration_v2_message_search s
            JOIN orchestration_v2_projection_messages m ON m.rowid = s.rowid
            JOIN orchestration_v2_projection_threads t ON t.thread_id = m.thread_id
            LEFT JOIN projection_projects p ON p.project_id = t.project_id
            WHERE orchestration_v2_message_search MATCH ?
              AND {thread_filter}
              {extra_like}
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            [fts_expr] + common_params + extra_params + [limit * 12],
        ).fetchall()
    else:
        like_clause = " AND ".join(
            "lower(COALESCE(json_extract(m.payload_json, '$.text'), '')) LIKE lower(?)" for _ in terms
        )
        like_params = [f"%{t}%" for t in terms]
        msg_rows = conn.execute(
            f"""
            SELECT
              t.thread_id, t.project_id, COALESCE(p.title, '') AS project_title,
              t.title, t.default_provider, t.created_at, t.updated_at, t.archived_at,
              m.role, m.created_at AS msg_created_at,
              json_extract(m.payload_json, '$.text') AS msg_text
            FROM orchestration_v2_projection_messages m
            JOIN orchestration_v2_projection_threads t ON t.thread_id = m.thread_id
            LEFT JOIN projection_projects p ON p.project_id = t.project_id
            WHERE m.streaming = 0
              AND (m.role = 'assistant' OR (m.role = 'user' AND COALESCE(json_extract(m.payload_json, '$.createdBy'), 'user') = 'user'))
              AND {thread_filter}
              AND ({like_clause})
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            common_params + like_params + [limit * 12],
        ).fetchall()

    for row in msg_rows:
        text = clean_message_text(row["msg_text"])
        if not text:
            continue
        snippet = build_snippet(text, terms)
        record_hit(row, snippet, 1.0, row["role"], row["msg_created_at"])

    ranked = sorted(
        results.values(),
        key=lambda item: (item["updated_at"], item["score"]),
        reverse=True,
    )
    # Prefer stronger matches when there are many hits, while keeping recent threads high.
    ranked = sorted(
        ranked,
        key=lambda item: (min(item["score"], 5.0), item["updated_at"]),
        reverse=True,
    )
    return ranked[:limit]


def resolve_thread_id(conn: sqlite3.Connection, ref: str) -> str:
    cleaned = ref.strip()
    if "/" in cleaned:
        cleaned = cleaned.rstrip("/").rsplit("/", 1)[-1]
    exact = conn.execute(
        "SELECT thread_id FROM orchestration_v2_projection_threads WHERE thread_id = ? AND deleted_at IS NULL",
        (cleaned,),
    ).fetchone()
    if exact:
        return exact["thread_id"]
    matches = conn.execute(
        "SELECT thread_id, title FROM orchestration_v2_projection_threads WHERE thread_id LIKE ? AND deleted_at IS NULL LIMIT 5",
        (cleaned + "%",),
    ).fetchall()
    if len(matches) == 1:
        return matches[0]["thread_id"]
    if len(matches) > 1:
        opts = ", ".join(m["thread_id"][:12] for m in matches)
        raise ValueError(f"Ambiguous thread prefix {ref!r}; matches: {opts}")
    raise NotFound(f"Thread {ref!r} not found")


def read_thread(
    conn: sqlite3.Connection,
    ref: str,
    *,
    offset: int = 0,
    limit: int = 40,
    max_chars: int = 3000,
    role: str | None = None,
) -> dict:
    thread_id = resolve_thread_id(conn, ref)
    trow = conn.execute(
        """
        SELECT
          t.thread_id, t.project_id, COALESCE(p.title, '') AS project_title,
          COALESCE(p.workspace_root, '') AS workspace_root,
          t.title, t.default_provider, t.created_at, t.updated_at, t.archived_at
        FROM orchestration_v2_projection_threads t
        LEFT JOIN projection_projects p ON p.project_id = t.project_id
        WHERE t.thread_id = ?
        """,
        (thread_id,),
    ).fetchone()
    if trow is None:
        raise NotFound(f"Thread {ref!r} not found")

    role_clause = ""
    params: list = [thread_id]
    if role:
        role_clause = " AND m.role = ?"
        params.append(role)

    mrows = conn.execute(
        f"""
        SELECT
          m.message_id, m.role, m.created_at, m.payload_json
        FROM orchestration_v2_projection_messages m
        WHERE m.thread_id = ?
          AND m.streaming = 0
          AND (m.role = 'assistant' OR (m.role = 'user' AND COALESCE(json_extract(m.payload_json, '$.createdBy'), 'user') = 'user'))
          {role_clause}
        ORDER BY m.created_at ASC, m.rowid ASC
        """,
        params,
    ).fetchall()

    messages: list[dict] = []
    for row in mrows:
        payload = json.loads(row["payload_json"])
        text = clean_message_text(payload.get("text"))
        if not text:
            continue
        truncated = False
        total_chars = len(text)
        if max_chars > 0 and total_chars > max_chars:
            text = text[:max_chars].rstrip() + f"\n... [truncated; {total_chars} chars total]"
            truncated = True
        messages.append(
            {
                "message_id": row["message_id"],
                "role": row["role"],
                "created_at": row["created_at"],
                "text": text,
                "truncated": truncated,
                "total_chars": total_chars,
            }
        )

    total = len(messages)
    start = max(0, offset)
    end = start + max(1, limit)
    page = messages[start:end]
    return {
        "thread_id": trow["thread_id"],
        "project_id": trow["project_id"],
        "project": trow["project_title"],
        "workspace_root": trow["workspace_root"],
        "title": trow["title"],
        "provider": trow["default_provider"],
        "created_at": trow["created_at"],
        "updated_at": trow["updated_at"],
        "archived": trow["archived_at"] is not None,
        "url": thread_url(trow["thread_id"]),
        "total_messages": total,
        "offset": start,
        "has_more": end < total,
        "next_offset": end if end < total else None,
        "messages": page,
    }


def recent_transcripts(
    conn: sqlite3.Connection,
    *,
    since: str | None = None,
    limit: int = 20,
    max_chars_per_thread: int = 5000,
) -> list[dict]:
    """Return compact transcripts for threads updated after `since` (chronological)."""
    since_iso = parse_since(since) if since else None
    params: list = []
    where = [
        "t.deleted_at IS NULL",
        "COALESCE(json_extract(t.payload_json, '$.lineage.relationshipToParent'), '') != 'subagent'",
    ]
    if since_iso:
        where.append("t.updated_at > ?")
        params.append(since_iso)
    rows = conn.execute(
        f"""
        SELECT t.thread_id
        FROM orchestration_v2_projection_threads t
        WHERE {' AND '.join(where)}
        ORDER BY t.updated_at ASC
        LIMIT ?
        """,
        params + [max(1, min(limit, 100))],
    ).fetchall()

    transcripts: list[dict] = []
    for row in rows:
        data = read_thread(conn, row["thread_id"], offset=0, limit=100, max_chars=1200)
        if not data["messages"]:
            continue
        # Keep the budget bounded per thread while preserving user messages preferentially.
        kept: list[dict] = []
        used = 0
        for msg in data["messages"]:
            piece = msg["text"]
            cap = 1200 if msg["role"] == "user" else 700
            if len(piece) > cap:
                piece = piece[:cap].rstrip() + "…"
            if used + len(piece) > max_chars_per_thread and kept:
                break
            kept.append({"role": msg["role"], "created_at": msg["created_at"], "text": piece})
            used += len(piece)
        transcripts.append(
            {
                "thread_id": data["thread_id"],
                "project": data["project"],
                "title": data["title"],
                "updated_at": data["updated_at"],
                "messages": kept,
            }
        )
    return transcripts


# ---------------------------------------------------------------- CLI formatting


def print_projects(items: list[dict]) -> None:
    if not items:
        print("No projects found.")
        return
    for item in items:
        tag = " [archived]" if item["archived"] else ""
        last = format_local(item["last_thread_at"]) or "-"
        print(f"{item['title']}{tag}  ({item['thread_count']} threads, last {last})  {item['workspace_root']}")


def print_threads(items: list[dict]) -> None:
    if not items:
        print("No threads found.")
        return
    for item in items:
        tag = " [archived]" if item["archived"] else ""
        proj = f"[{item['project']}] " if item["project"] else ""
        print(
            f"{item['thread_id'][:8]}  {format_local(item['updated_at'])}  "
            f"{proj}{item['title']}{tag}  ({item['message_count']} msgs)"
        )


def print_search(items: list[dict]) -> None:
    if not items:
        print("No matching threads.")
        return
    for item in items:
        tag = " [archived]" if item["archived"] else ""
        proj = f"[{item['project']}] " if item["project"] else ""
        print(
            f"{item['thread_id']}  {format_local(item['updated_at'])}  "
            f"{proj}{item['title']}{tag}  ({item['match_count']} hits)"
        )
        for match in item["matches"]:
            print(f"  ({match['where']} @ {format_local(match['created_at'])}) {match['snippet']}")


def print_read(data: dict) -> None:
    tag = " [archived]" if data["archived"] else ""
    proj = f" [{data['project']}]" if data["project"] else ""
    print(f"# {data['title']}{proj}{tag}")
    print(f"Thread: {data['thread_id']}  ({data['url']})")
    print(
        f"Updated: {format_local(data['updated_at'])}  "
        f"Provider: {data['provider']}  "
        f"Messages: {data['offset'] + 1}-{data['offset'] + len(data['messages'])} of {data['total_messages']}"
    )
    print()
    for msg in data["messages"]:
        role = msg["role"].upper()
        print(f"## {role} ({format_local(msg['created_at'])})")
        print(msg["text"])
        print()
    if data["has_more"]:
        print(f"(More messages available; pass --offset {data['next_offset']})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="t3-history",
        description="Read-only search and transcript viewer for T3 Code chat history.",
    )
    parser.add_argument("--db", type=Path, default=None, help="Path to T3 statev2.sqlite")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_proj = sub.add_parser("projects", help="List T3 projects")
    p_proj.add_argument("--json", action="store_true")

    p_list = sub.add_parser("list", help="List T3 threads newest-first across projects")
    p_list.add_argument("--project", help="Filter by project ID, title, or path substring")
    p_list.add_argument("--active-only", action="store_true", help="Exclude archived threads")
    p_list.add_argument("--include-subagents", action="store_true")
    p_list.add_argument("--since", help="Only threads updated since (e.g. 7d, 24h, 2026-11-01)")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--offset", type=int, default=0)
    p_list.add_argument("--json", action="store_true")

    p_search = sub.add_parser("search", help="Search past T3 threads by title, project, and message text")
    p_search.add_argument("query", nargs="+", help="Search terms")
    p_search.add_argument("--project", help="Filter by project ID, title, or path substring")
    p_search.add_argument("--active-only", action="store_true", help="Exclude archived threads")
    p_search.add_argument("--include-subagents", action="store_true")
    p_search.add_argument("--since", help="Only threads updated since (e.g. 30d, 2026-11-01)")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--json", action="store_true")

    p_read = sub.add_parser("read", help="Read messages from a T3 thread by ID or unique prefix")
    p_read.add_argument("thread", help="Thread ID, prefix, or T3 URL")
    p_read.add_argument("--offset", type=int, default=0)
    p_read.add_argument("--limit", type=int, default=40)
    p_read.add_argument("--max-chars", type=int, default=3000, help="Max chars per message (0 = unlimited)")
    p_read.add_argument("--role", choices=("user", "assistant"))
    p_read.add_argument("--json", action="store_true")

    p_recent = sub.add_parser("recent-transcripts", help="Export compact transcripts updated since a timestamp")
    p_recent.add_argument("--since", help="ISO timestamp or relative duration (e.g. 24h)")
    p_recent.add_argument("--limit", type=int, default=20)
    p_recent.add_argument("--max-chars-per-thread", type=int, default=5000)
    p_recent.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        conn = open_db(args.db)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        if args.cmd == "projects":
            items = list_projects(conn)
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
            else:
                print_projects(items)
            return 0

        if args.cmd == "list":
            items = list_threads(
                conn,
                project=args.project,
                active_only=args.active_only,
                include_subagents=args.include_subagents,
                since=args.since,
                limit=args.limit,
                offset=args.offset,
            )
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
            else:
                print_threads(items)
            return 0

        if args.cmd == "search":
            items = search_threads(
                conn,
                " ".join(args.query),
                project=args.project,
                active_only=args.active_only,
                include_subagents=args.include_subagents,
                since=args.since,
                limit=args.limit,
            )
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
            else:
                print_search(items)
            return 0

        if args.cmd == "read":
            data = read_thread(
                conn,
                args.thread,
                offset=args.offset,
                limit=args.limit,
                max_chars=args.max_chars,
                role=args.role,
            )
            if args.json:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                print_read(data)
            return 0

        if args.cmd == "recent-transcripts":
            items = recent_transcripts(
                conn,
                since=args.since,
                limit=args.limit,
                max_chars_per_thread=args.max_chars_per_thread,
            )
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return 0
    except (NotFound, ValueError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
