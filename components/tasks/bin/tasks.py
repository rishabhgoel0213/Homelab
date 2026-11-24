#!/usr/bin/env python3
"""Weekly task board shared by a tailnet web page and the `tasks` CLI.

Every interface reads and writes one SQLite database. Weeks start on Sunday and
are identified by that Sunday's ISO date (for example 2026-11-15).
"""

import argparse
import json
import os
import re
import secrets
import sqlite3
import sys
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

VERSION = "1.0.0"
STATE = Path(os.environ.get("TASKS_STATE", "/srv/state/tasks"))
TIMEZONE = ZoneInfo(os.environ.get("TASKS_TIMEZONE", "America/New_York"))
WEB = Path(os.environ.get("TASKS_WEB", Path(__file__).resolve().parent.parent / "web"))
URL = os.environ.get("TASKS_URL", "")

DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
DAY_ALIASES = {name: index for index, name in enumerate(DAYS)}
DAY_ALIASES.update({name.lower(): index for index, name in enumerate(DAY_NAMES)})
DAY_ALIASES.update({"tues": 2, "weds": 3, "thur": 4, "thurs": 4})
ANYTIME = {"", "any", "anytime", "week", "this week", "unscheduled", "none"}
SOURCES = ("me", "agent")
MAX_TITLE = 500
MAX_NOTES = 10000
MAX_BODY = 256 * 1024


class NotFound(LookupError):
    pass


# ---------------------------------------------------------------- dates


def today():
    return datetime.now(TIMEZONE).date()


def week_start(day):
    return day - timedelta(days=(day.weekday() + 1) % 7)


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Invalid date {value!r}; use YYYY-MM-DD") from None


def resolve_week(value=None, base=None):
    """Return the Sunday that starts the requested week."""
    current = week_start(base or today())
    if value is None:
        return current
    if not isinstance(value, str):
        raise ValueError("week must be a string")
    text = value.strip().lower()
    if text in ("", "this", "current", "this week", "now"):
        return current
    if text in ("next", "next week"):
        return current + timedelta(days=7)
    if text in ("last", "previous", "prev", "last week"):
        return current - timedelta(days=7)
    if re.fullmatch(r"[+-]\d{1,3}", text):
        return current + timedelta(days=7 * int(text))
    return week_start(parse_date(text))


def resolve_day(value, week):
    """Return (week_sunday, day_index_or_None) for a day name, index or date."""
    if value is None:
        return week, None
    if isinstance(value, bool):
        raise ValueError("day must be a weekday name, 0-6, or a date")
    if isinstance(value, int):
        if not 0 <= value <= 6:
            raise ValueError("day index must be 0 (Sunday) through 6 (Saturday)")
        return week, value
    if not isinstance(value, str):
        raise ValueError("day must be a weekday name, 0-6, or a date")
    text = value.strip().lower()
    if text in ANYTIME:
        return week, None
    if text in DAY_ALIASES:
        return week, DAY_ALIASES[text]
    if text in ("today", "tomorrow", "tmrw", "yesterday"):
        offset = {"today": 0, "tomorrow": 1, "tmrw": 1, "yesterday": -1}[text]
        target = today() + timedelta(days=offset)
    else:
        target = parse_date(text)
    return week_start(target), (target.weekday() + 1) % 7


def parse_quick(text):
    """Split quick-add text such as 'fri: call dentist' into (day, title)."""
    match = re.match(r"^\s*([A-Za-z]+|\d{4}-\d{2}-\d{2})\s*:\s*(.+)$", text, re.S)
    if match:
        prefix = match.group(1).lower()
        if prefix in DAY_ALIASES or prefix in ("today", "tomorrow", "tmrw", "anytime", "week") \
                or re.fullmatch(r"\d{4}-\d{2}-\d{2}", prefix):
            return prefix, match.group(2).strip()
    return None, text.strip()


# ---------------------------------------------------------------- storage


def utc_now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(STATE / "tasks.db", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=15000")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks(
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',
          week TEXT NOT NULL,
          day INTEGER CHECK(day IS NULL OR day BETWEEN 0 AND 6),
          done INTEGER NOT NULL DEFAULT 0,
          position REAL NOT NULL,
          source TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          completed_at TEXT);
        CREATE INDEX IF NOT EXISTS tasks_week ON tasks(week, day, position);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
        INSERT OR IGNORE INTO meta VALUES('rev', 0);
    """)
    return db


def revision(db):
    return db.execute("SELECT value FROM meta WHERE key='rev'").fetchone()[0]


def bump(db):
    db.execute("UPDATE meta SET value=value+1 WHERE key='rev'")


def task_value(row):
    week = date.fromisoformat(row["week"])
    day = row["day"]
    return {
        "id": row["id"],
        "title": row["title"],
        "notes": row["notes"],
        "week": row["week"],
        "day": None if day is None else DAYS[day],
        "date": None if day is None else (week + timedelta(days=day)).isoformat(),
        "done": bool(row["done"]),
        "position": row["position"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def get_row(db, task_id):
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("task_id is required")
    row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id.strip(),)).fetchone()
    if row is None:
        raise NotFound(f"No task with id {task_id!r}")
    return row


def clean_title(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("title must be a non-empty string")
    value = " ".join(value.split())
    if len(value) > MAX_TITLE:
        raise ValueError(f"title is longer than {MAX_TITLE} characters")
    return value


def clean_notes(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("notes must be a string")
    if len(value) > MAX_NOTES:
        raise ValueError(f"notes are longer than {MAX_NOTES} characters")
    return value.strip()


def next_position(db, week, day):
    row = db.execute("SELECT MAX(position) FROM tasks WHERE week=? AND day IS ?",
                     (week.isoformat(), day)).fetchone()
    return (row[0] or 0) + 1


def new_id(db):
    while True:
        task_id = secrets.token_hex(3)
        if db.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone() is None:
            return task_id


def list_week(db, week=None, include_done=True):
    sunday = resolve_week(week)
    rows = db.execute(
        "SELECT * FROM tasks WHERE week=? ORDER BY day IS NOT NULL, day, position, created_at",
        (sunday.isoformat(),)).fetchall()
    tasks = [task_value(row) for row in rows]
    done = sum(task["done"] for task in tasks)
    previous = (sunday - timedelta(days=7)).isoformat()
    carry = db.execute("SELECT COUNT(*) FROM tasks WHERE week=? AND done=0", (previous,)).fetchone()[0]
    if not include_done:
        tasks = [task for task in tasks if not task["done"]]
    return {
        "week": sunday.isoformat(),
        "week_end": (sunday + timedelta(days=6)).isoformat(),
        "today": today().isoformat(),
        "rev": revision(db),
        "days": [{"day": DAYS[i], "name": DAY_NAMES[i], "date": (sunday + timedelta(days=i)).isoformat()}
                 for i in range(7)],
        "summary": {"total": len(rows), "done": done, "open": len(rows) - done},
        "previous_unfinished": carry,
        "tasks": tasks,
    }


def add_task(db, item, source, week=None):
    if source not in SOURCES:
        raise ValueError("source must be 'me' or 'agent'")
    if isinstance(item, str):
        item = {"text": item}
    if not isinstance(item, dict):
        raise ValueError("each task must be an object or quick-add string")
    unknown = set(item) - {"title", "text", "notes", "day", "week"}
    if unknown:
        raise ValueError(f"Unknown task fields: {', '.join(sorted(unknown))}")
    day = item.get("day")
    title = item.get("title")
    if title is None and item.get("text") is not None:
        if not isinstance(item["text"], str):
            raise ValueError("text must be a string")
        parsed_day, title = parse_quick(item["text"])
        day = day if day is not None else parsed_day
    sunday, day_index = resolve_day(day, resolve_week(item.get("week", week)))
    now = utc_now()
    task_id = new_id(db)
    db.execute(
        "INSERT INTO tasks(id,title,notes,week,day,done,position,source,created_at,updated_at)"
        " VALUES(?,?,?,?,?,0,?,?,?,?)",
        (task_id, clean_title(title), clean_notes(item.get("notes")), sunday.isoformat(), day_index,
         next_position(db, sunday, day_index), source, now, now))
    return task_value(get_row(db, task_id))


def add_tasks(db, items, source, week=None):
    if not isinstance(items, list) or not items:
        raise ValueError("tasks must be a non-empty list")
    if len(items) > 200:
        raise ValueError("add at most 200 tasks at once")
    with db:
        created = [add_task(db, item, source, week) for item in items]
        bump(db)
    return created


def update_task(db, task_id, fields):
    unknown = set(fields) - {"title", "notes", "day", "week", "done", "position"}
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    with db:
        row = get_row(db, task_id)
        changes = {}
        if "title" in fields:
            changes["title"] = clean_title(fields["title"])
        if "notes" in fields:
            changes["notes"] = clean_notes(fields["notes"])
        if "day" in fields or "week" in fields:
            base = resolve_week(fields["week"]) if fields.get("week") is not None \
                else date.fromisoformat(row["week"])
            day = fields["day"] if "day" in fields else row["day"]
            sunday, day_index = resolve_day(day, base)
            if (sunday.isoformat(), day_index) != (row["week"], row["day"]):
                changes["week"] = sunday.isoformat()
                changes["day"] = day_index
                changes["position"] = next_position(db, sunday, day_index)
        if "position" in fields:
            if isinstance(fields["position"], bool) or not isinstance(fields["position"], (int, float)):
                raise ValueError("position must be a number")
            changes["position"] = float(fields["position"])
        if "done" in fields:
            if not isinstance(fields["done"], bool):
                raise ValueError("done must be true or false")
            if fields["done"] != bool(row["done"]):
                changes["done"] = int(fields["done"])
                changes["completed_at"] = utc_now() if fields["done"] else None
        if changes:
            changes["updated_at"] = utc_now()
            assignments = ", ".join(f"{key}=?" for key in changes)
            db.execute(f"UPDATE tasks SET {assignments} WHERE id=?", (*changes.values(), row["id"]))
            bump(db)
        return task_value(get_row(db, row["id"]))


def delete_task(db, task_id):
    with db:
        row = get_row(db, task_id)
        db.execute("DELETE FROM tasks WHERE id=?", (row["id"],))
        bump(db)
    return {"deleted": task_value(row)}


def reorder(db, week, day, ids):
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ValueError("ids must be a list of task ids")
    sunday, day_index = resolve_day(day, resolve_week(week))
    with db:
        now = utc_now()
        for position, task_id in enumerate(ids, 1):
            row = get_row(db, task_id)
            if (row["week"], row["day"], row["position"]) != (sunday.isoformat(), day_index, position):
                db.execute("UPDATE tasks SET week=?, day=?, position=?, updated_at=? WHERE id=?",
                           (sunday.isoformat(), day_index, position, now, row["id"]))
        bump(db)
    return list_week(db, sunday.isoformat())


def carry_over(db, from_week=None, to_week=None):
    source = resolve_week(from_week if from_week is not None else "last")
    target = resolve_week(to_week) if to_week is not None else source + timedelta(days=7)
    if source == target:
        raise ValueError("from_week and to_week are the same week")
    with db:
        rows = db.execute("SELECT * FROM tasks WHERE week=? AND done=0 ORDER BY day IS NOT NULL, day, position",
                          (source.isoformat(),)).fetchall()
        position = next_position(db, target, None)
        now = utc_now()
        for offset, row in enumerate(rows):
            db.execute("UPDATE tasks SET week=?, day=NULL, position=?, updated_at=? WHERE id=?",
                       (target.isoformat(), position + offset, now, row["id"]))
        if rows:
            bump(db)
    return {"from_week": source.isoformat(), "to_week": target.isoformat(), "moved": len(rows),
            "tasks": [task_value(get_row(db, row["id"])) for row in rows]}


# ---------------------------------------------------------------- Structured CLI actions


ACTIONS = ("list_tasks", "add_tasks", "update_task", "delete_task", "carry_over")


def dispatch(db, name, args, source="agent"):
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    if name == "list_tasks":
        return list_week(db, args.get("week"), args.get("include_done", True) is not False)
    if name == "add_tasks":
        return {"created": add_tasks(db, args.get("tasks"), source, args.get("week")),
                "board": URL or None}
    if name == "update_task":
        fields = {key: value for key, value in args.items() if key != "task_id"}
        return update_task(db, args.get("task_id"), fields)
    if name == "delete_task":
        return delete_task(db, args.get("task_id"))
    if name == "carry_over":
        return carry_over(db, args.get("from_week"), args.get("to_week"))
    raise ValueError(f"Unknown action {name!r}")


# ---------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "tasks/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("TASKS_ACCESS_LOG"):
            super().log_message(fmt, *args)

    def send(self, status, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; "
                         "base-uri 'none'; form-action 'self'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("Request body is too large")
        if not length:
            return {}
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def same_origin(self):
        """Reject cross-site writes; a JSON content type also forces a CORS preflight."""
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return False
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return False
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == self.headers.get("Host")

    def handle_api(self):
        url = urlparse(self.path)
        query = {key: values[-1] for key, values in parse_qs(url.query).items()}
        parts = [part for part in url.path.split("/") if part]
        if self.command in ("GET", "HEAD"):
            if url.path in ("/", "/index.html"):
                return self.send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            if url.path == "/healthz":
                return self.send(200, {"ok": True, "version": VERSION})
            db = connect()
            try:
                if url.path == "/api/week":
                    return self.send(200, list_week(db, query.get("week")))
                if url.path == "/api/rev":
                    return self.send(200, {"rev": revision(db)})
            finally:
                db.close()
            return self.send(404, {"error": "Not found"})
        if not self.same_origin():
            return self.send(403, {"error": "Cross-site or non-JSON request refused"})
        payload = self.body()
        db = connect()
        try:
            if self.command == "POST" and parts == ["api", "tasks"]:
                return self.send(201, add_tasks(db, [payload], "me")[0])
            if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                if self.command == "PATCH":
                    return self.send(200, update_task(db, parts[2], payload))
                if self.command == "DELETE":
                    return self.send(200, delete_task(db, parts[2]))
            if self.command == "POST" and parts == ["api", "reorder"]:
                return self.send(200, reorder(db, payload.get("week"), payload.get("day"), payload.get("ids")))
            if self.command == "POST" and parts == ["api", "carry"]:
                return self.send(200, carry_over(db, payload.get("from_week"), payload.get("to_week")))
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

    do_GET = do_HEAD = do_POST = do_PATCH = do_DELETE = dispatch_request


def serve(host, port):
    connect().close()
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"tasks serving on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


# ---------------------------------------------------------------- CLI


def format_week(board):
    start, end = date.fromisoformat(board["week"]), date.fromisoformat(board["week_end"])
    summary = board["summary"]
    lines = [f"Week of {start:%a %b %-d} - {end:%a %b %-d, %Y}  ({summary['done']}/{summary['total']} done)"]
    if URL:
        lines.append(URL)
    groups = [(None, "Anytime this week")] + [(d["day"], f"{d['name']} {date.fromisoformat(d['date']):%b %-d}")
                                              for d in board["days"]]
    for day, label in groups:
        tasks = [task for task in board["tasks"] if task["day"] == day]
        if not tasks:
            continue
        lines.append("")
        lines.append(label + (" (today)" if day and next(d for d in board["days"] if d["day"] == day)["date"] == board["today"] else ""))
        for task in tasks:
            mark = "x" if task["done"] else " "
            agent = "  [agent]" if task["source"] == "agent" else ""
            lines.append(f"  [{mark}] {task['id']}  {task['title']}{agent}")
            for note in task["notes"].splitlines():
                lines.append(f"             {note}")
    if not board["tasks"]:
        lines.append("")
        lines.append("No tasks yet.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(prog="tasks", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=SOURCES, default="agent",
                        help="who is adding tasks from the CLI (default: agent)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("serve", help="serve the web board and JSON API")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8740)
    show = sub.add_parser("list", help="show a week (default: this week)")
    show.add_argument("week", nargs="?")
    show.add_argument("--json", action="store_true")
    add = sub.add_parser("add", help="add tasks; each argument is one task, e.g. 'fri: call dentist'")
    add.add_argument("text", nargs="+")
    add.add_argument("--week")
    add.add_argument("--notes")
    for name, help_text in (("done", "mark tasks done"), ("undo", "mark tasks not done"), ("rm", "delete tasks")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("ids", nargs="+")
    move = sub.add_parser("move", help="move a task to a day (sun..sat, today, a date, or anytime)")
    move.add_argument("id")
    move.add_argument("day")
    move.add_argument("--week")
    carry = sub.add_parser("carry", help="move unfinished tasks from last week into this week")
    carry.add_argument("--from", dest="from_week")
    carry.add_argument("--to", dest="to_week")
    call = sub.add_parser("call", help="invoke a structured task action with JSON arguments")
    call.add_argument("name", choices=ACTIONS)
    call.add_argument("--arguments", default="{}", help="JSON object; use '-' to read stdin")
    args = parser.parse_args()

    if args.command == "serve":
        return serve(args.host, args.port)
    db = connect()
    try:
        if args.command == "list":
            board = list_week(db, args.week)
            print(json.dumps(board, indent=2) if args.json else format_week(board))
        elif args.command == "add":
            items = [{"text": text, **({"notes": args.notes} if args.notes else {})} for text in args.text]
            for task in add_tasks(db, items, args.source, args.week):
                print(f"added {task['id']}  {task['day'] or 'anytime'}  {task['title']}")
        elif args.command in ("done", "undo"):
            for task_id in args.ids:
                task = update_task(db, task_id, {"done": args.command == "done"})
                print(f"{'done' if task['done'] else 'open'} {task['id']}  {task['title']}")
        elif args.command == "rm":
            for task_id in args.ids:
                print(f"deleted {delete_task(db, task_id)['deleted']['id']}")
        elif args.command == "move":
            fields = {"day": args.day, **({"week": args.week} if args.week else {})}
            task = update_task(db, args.id, fields)
            print(f"moved {task['id']} to {task['date'] or 'anytime, week of ' + task['week']}")
        elif args.command == "carry":
            result = carry_over(db, args.from_week, args.to_week)
            print(f"moved {result['moved']} unfinished task(s) from {result['from_week']} to {result['to_week']}")
        elif args.command == "call":
            raw = sys.stdin.read() if args.arguments == "-" else args.arguments
            print(json.dumps(dispatch(db, args.name, json.loads(raw), args.source), indent=2, ensure_ascii=False))
    except (ValueError, LookupError) as error:
        print(f"tasks: {error}", file=sys.stderr)
        return 2
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
