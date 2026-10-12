#!/usr/bin/env python3
"""Local, durable Codex jobs. stdio MCP manages jobs; systemd calls tick."""

import argparse
import fcntl
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


VERSION = "0.1.0"
STATE = Path(os.environ.get("CODEX_SCHEDULER_STATE", "/srv/state/codex-scheduler"))
ROOTS = json.loads(os.environ.get(
    "CODEX_SCHEDULER_ROOTS",
    '["/home/rishabh/Projects", "/home/rishabh/Documents", "/srv/ops"]',
))
CODEX = os.environ.get("CODEX_SCHEDULER_CODEX", "/run/current-system/sw/bin/codex")


def utc_now():
    return datetime.now(UTC)


def stamp(value):
    return value.isoformat() if value else None


def parse_date(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp must be an ISO 8601 string with a timezone")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include a timezone offset")
    return result.astimezone(UTC)


def validate_schedule(schedule):
    if not isinstance(schedule, dict):
        raise ValueError("schedule must be an object")
    frequency = schedule.get("frequency")
    if frequency == "once":
        if set(schedule) != {"frequency", "run_at"}:
            raise ValueError("Once schedules require only frequency and run_at")
        return {"frequency": frequency, "run_at": stamp(parse_date(schedule["run_at"]))}
    if frequency not in ("daily", "weekly"):
        raise ValueError("frequency must be daily, weekly, or once")
    expected = {"frequency", "time", "timezone"}
    if frequency == "weekly":
        expected.add("weekdays")
    if set(schedule) != expected:
        raise ValueError(f"Schedule fields must be: {', '.join(sorted(expected))}")
    if not isinstance(schedule["time"], str) or not re.fullmatch(
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", schedule["time"]
    ):
        raise ValueError("time must be HH:MM in 24-hour format")
    ZoneInfo(schedule["timezone"])
    result = dict(schedule)
    if frequency == "weekly":
        days = schedule["weekdays"]
        if not isinstance(days, list) or not days or any(
            type(day) is not int or day not in range(1, 8) for day in days
        ):
            raise ValueError("weekdays must contain ISO weekday numbers, Monday=1 to Sunday=7")
        result["weekdays"] = sorted(set(days))
    return result


def next_time(schedule, after):
    """Strictly later than after; skip nonexistent DST times, first fold only."""
    if schedule["frequency"] == "once":
        at = parse_date(schedule["run_at"])
        return at if at > after else None
    zone = ZoneInfo(schedule["timezone"])
    local = after.astimezone(zone)
    hour, minute = map(int, schedule["time"].split(":"))
    for offset in range(15):
        date = local.date() + timedelta(days=offset)
        if schedule["frequency"] == "weekly" and date.isoweekday() not in schedule["weekdays"]:
            continue
        candidate = datetime(date.year, date.month, date.day, hour, minute, tzinfo=zone)
        at = candidate.astimezone(UTC)
        if at.astimezone(zone).replace(tzinfo=None) != candidate.replace(tzinfo=None):
            continue
        if at > after:
            return at
    raise ValueError("No valid occurrence found in the next two weeks")


def validate_project(value):
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError("project must be an absolute directory path")
    project = Path(value).resolve(strict=True)
    if not project.is_dir() or not any(project.is_relative_to(Path(root).resolve()) for root in ROOTS):
        raise ValueError("project must be a directory under an allowed project root")
    if any(project == Path(root).resolve() for root in ROOTS if root != "/srv/ops"):
        raise ValueError("Select a specific project, not the whole Projects or Documents root")
    return str(project)


def validate_job(data):
    for key, maximum in (("name", 120), ("prompt", 100_000)):
        if not isinstance(data[key], str) or not data[key].strip() or len(data[key]) > maximum:
            raise ValueError(f"{key} must be nonempty and at most {maximum} characters")
    data["name"] = data["name"].strip()
    data["project"] = validate_project(data["project"])
    data["schedule"] = validate_schedule(data["schedule"])
    if type(data["enabled"]) is not bool:
        raise ValueError("enabled must be a boolean")
    if type(data["timeout_seconds"]) is not int or not 30 <= data["timeout_seconds"] <= 7200:
        raise ValueError("timeout_seconds must be between 30 and 7200")
    if data["model"] is not None and (
        not isinstance(data["model"], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", data["model"])
    ):
        raise ValueError("model must be a model identifier or null")
    if data["reasoning_effort"] not in (None, "minimal", "low", "medium", "high", "xhigh", "max", "ultra"):
        raise ValueError("Invalid reasoning_effort")
    if data["end_at"] is not None:
        data["end_at"] = stamp(parse_date(data["end_at"]))
    return data


def connect():
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    (STATE / "runs").mkdir(mode=0o700, exist_ok=True)
    db = sqlite3.connect(STATE / "scheduler.db", timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, data TEXT NOT NULL,
            next_run_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            status TEXT NOT NULL, trigger TEXT NOT NULL, queued_at TEXT NOT NULL,
            started_at TEXT, finished_at TEXT, exit_code INTEGER,
            summary TEXT, error TEXT, log_path TEXT, thread_id TEXT
        );
        CREATE INDEX IF NOT EXISTS runs_status ON runs(status, queued_at);
        CREATE INDEX IF NOT EXISTS runs_job ON runs(job_id, queued_at);
    """)
    return db


def job_value(row):
    if row is None:
        raise ValueError("Job not found")
    return {**json.loads(row["data"]), **{key: row[key] for key in (
        "id", "next_run_at", "created_at", "updated_at"
    )}}


def get_job(db, job_id):
    return job_value(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def calculate_next(data, now):
    at = next_time(data["schedule"], now) if data["enabled"] else None
    if at and data["end_at"] and at > parse_date(data["end_at"]):
        at = None
    return stamp(at)


def save_job(db, data, job_id=None):
    data = validate_job(data)
    now = utc_now()
    at = calculate_next(data, now)
    if data["enabled"] and at is None:
        raise ValueError("No future occurrence before end_at; create paused or choose a future schedule")
    if job_id:
        db.execute("UPDATE jobs SET name=?,data=?,next_run_at=?,updated_at=? WHERE id=?",
                   (data["name"], json.dumps(data), at, stamp(now), job_id))
    else:
        job_id = str(uuid.uuid4())
        db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?)",
                   (job_id, data["name"], json.dumps(data), at, stamp(now), stamp(now)))
    return get_job(db, job_id)


def queue_run(db, job_id, trigger, now):
    existing = db.execute(
        "SELECT * FROM runs WHERE job_id=? AND status IN ('queued','running')", (job_id,)
    ).fetchone()
    if existing:
        return dict(existing)
    run_id = str(uuid.uuid4())
    db.execute("INSERT INTO runs(id,job_id,status,trigger,queued_at) VALUES(?,?,'queued',?,?)",
               (run_id, job_id, trigger, stamp(now)))
    return dict(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())


def dispatch(db, name, args):
    schema = next((tool["inputSchema"] for tool in TOOLS if tool["name"] == name), None)
    if schema is None:
        raise ValueError(f"Unknown tool: {name}")
    if not isinstance(args, dict) or set(args) - set(schema["properties"]):
        raise ValueError("Unknown arguments")
    if set(schema.get("required", [])) - set(args):
        raise ValueError("Missing required arguments")
    if "job_id" in args:
        if not isinstance(args["job_id"], str):
            raise ValueError("job_id must be a string")
        get_job(db, args["job_id"])
    if name == "list_jobs":
        return {"jobs": [job_value(row) for row in db.execute("SELECT * FROM jobs ORDER BY created_at")]}
    if name == "get_job":
        return get_job(db, args["job_id"])
    if name == "get_runs":
        limit = args.get("limit", 10)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        where, values = ("WHERE job_id=?", [args["job_id"]]) if "job_id" in args else ("", [])
        rows = db.execute(f"SELECT * FROM runs {where} ORDER BY queued_at DESC LIMIT ?", [*values, limit])
        return {"runs": [dict(row) for row in rows]}
    db.execute("BEGIN IMMEDIATE")
    try:
        if name == "create_job":
            data = {"enabled": True, "end_at": None, "timeout_seconds": 1800,
                    "model": None, "reasoning_effort": None, **args}
            result = save_job(db, data)
        elif name == "update_job":
            data = json.loads(db.execute("SELECT data FROM jobs WHERE id=?", (args["job_id"],)).fetchone()[0])
            data.update({key: value for key, value in args.items() if key != "job_id"})
            result = save_job(db, data, args["job_id"])
            # Queued work must not execute an outdated or disabled definition.
            db.execute("UPDATE runs SET status='cancelled',finished_at=?,error=? WHERE job_id=? AND status='queued'",
                       (stamp(utc_now()), "Job updated before execution", args["job_id"]))
        elif name == "pause_job":
            job = get_job(db, args["job_id"])
            data = json.loads(db.execute("SELECT data FROM jobs WHERE id=?", (job["id"],)).fetchone()[0])
            data["enabled"] = False
            result = save_job(db, data, job["id"])
            db.execute("UPDATE runs SET status='cancelled',finished_at=?,error=? WHERE job_id=? AND status='queued'",
                       (stamp(utc_now()), "Job paused before execution", job["id"]))
            result["note"] = "Queued runs cancelled. An already running job continues until completion or timeout."
        elif name == "run_now":
            result = queue_run(db, args["job_id"], "manual", utc_now())
        elif name == "delete_job":
            if db.execute("SELECT 1 FROM runs WHERE job_id=? AND status='running'", (args["job_id"],)).fetchone():
                raise ValueError("Wait for the active run to finish before deleting this job")
            if get_job(db, args["job_id"])["enabled"]:
                raise ValueError("Pause the job before deleting it")
            db.execute("DELETE FROM jobs WHERE id=?", (args["job_id"],))
            result = {"deleted": args["job_id"], "note": "Run records removed; log files retained."}
        else:
            raise ValueError(f"Unknown tool: {name}")
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def enqueue_due(db, now):
    for row in db.execute("SELECT * FROM jobs WHERE next_run_at<=?", (stamp(now),)).fetchall():
        job = job_value(row)
        data = json.loads(row["data"])
        if data["enabled"] and (not data["end_at"] or now <= parse_date(data["end_at"])):
            queue_run(db, job["id"], "scheduled", now)
        at = calculate_next(data, now)
        if at is None:
            data["enabled"] = False
        db.execute("UPDATE jobs SET data=?,next_run_at=?,updated_at=? WHERE id=?",
                   (json.dumps(data), at, stamp(now), job["id"]))


def codex_command(job, summary_path):
    command = [CODEX, "exec", "--skip-git-repo-check", "--sandbox", "workspace-write",
               "--cd", job["project"], "--json", "--output-last-message", str(summary_path),
               "-c", 'approval_policy="on-request"',
               "-c", 'approvals_reviewer="auto_review"',
               "-c", "mcp_servers.codex-scheduler.enabled=false"]
    if job["model"]:
        command.extend(["--model", job["model"]])
    if job["reasoning_effort"]:
        command.extend(["-c", f'model_reasoning_effort="{job["reasoning_effort"]}"'])
    command.append("-")
    return command


def execute_run(db, run, job):
    log_path = STATE / "runs" / f'{run["id"]}.jsonl'
    summary_path = STATE / "runs" / f'{run["id"]}.txt'
    status, error, exit_code, thread_id = "failed", None, None, None
    try:
        # Recheck symlinks and existence at execution, not only at job creation.
        job["project"] = validate_project(job["project"])
        with log_path.open("wb") as output:
            process = subprocess.Popen(codex_command(job, summary_path), stdin=subprocess.PIPE,
                                       stdout=output, stderr=output, start_new_session=True)
            try:
                process.communicate(job["prompt"].encode(), timeout=job["timeout_seconds"])
                exit_code = process.returncode
                status = "succeeded" if exit_code == 0 else "failed"
                if exit_code:
                    error = f"Codex exited with status {exit_code}; inspect log_path"
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                exit_code, status, error = process.returncode, "timed_out", "Run exceeded timeout_seconds"
        with log_path.open() as output:
            for line in output:
                try:
                    event = json.loads(line)
                    if isinstance(event, dict) and event.get("type") == "thread.started":
                        thread_id = event.get("thread_id")
                        break
                except json.JSONDecodeError:
                    continue
    except Exception as exception:
        error = str(exception)
    summary = summary_path.read_text()[:32_000] if summary_path.exists() else None
    if status == "succeeded" and not summary:
        status, error = "failed", "Codex exited successfully without a final summary"
    db.execute("UPDATE runs SET status=?,finished_at=?,exit_code=?,summary=?,error=?,log_path=?,thread_id=? WHERE id=?",
               (status, stamp(utc_now()), exit_code, summary, error, str(log_path), thread_id, run["id"]))


def tick():
    db = connect()
    with (STATE / "dispatcher.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            db.close()
            return 0
        try:
            now = utc_now()
            db.execute("BEGIN IMMEDIATE")
            # The global lock proves a previous dispatcher is no longer running.
            db.execute("UPDATE runs SET status='interrupted',finished_at=?,error=? WHERE status='running'",
                       (stamp(now), "Dispatcher stopped before recording completion; no automatic replay"))
            enqueue_due(db, now)
            run = db.execute("SELECT * FROM runs WHERE status='queued' ORDER BY queued_at LIMIT 1").fetchone()
            if run:
                job = get_job(db, run["job_id"])
                db.execute("UPDATE runs SET status='running',started_at=? WHERE id=?", (stamp(now), run["id"]))
            db.commit()
            if run:
                execute_run(db, dict(run), job)
        finally:
            if db.in_transaction:
                db.rollback()
            db.close()
    return 0


def tool(name, description, properties, required=(), readonly=False):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties,
                            "required": list(required), "additionalProperties": False},
            "annotations": {"readOnlyHint": readonly, "destructiveHint": name == "delete_job",
                            "openWorldHint": name == "run_now"}}


JOB_ID = {"job_id": {"type": "string", "description": "Exact job ID returned by create_job or list_jobs"}}
FIELDS = {
    "name": {"type": "string", "description": "Unique descriptive job name"},
    "project": {"type": "string", "description": "Absolute existing project directory"},
    "prompt": {"type": "string", "description": "Complete durable instructions for each fresh Codex run"},
    "schedule": {"type": "object", "description": "Daily/weekly use time HH:MM and an IANA timezone; weekly adds weekdays Monday=1 to Sunday=7. Once uses run_at with an explicit timezone offset.",
                 "oneOf": [
                     {"properties": {"frequency": {"const": "daily"}, "time": {"type": "string"}, "timezone": {"type": "string"}}, "required": ["frequency", "time", "timezone"], "additionalProperties": False},
                     {"properties": {"frequency": {"const": "weekly"}, "time": {"type": "string"}, "timezone": {"type": "string"}, "weekdays": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 7}, "minItems": 1}}, "required": ["frequency", "time", "timezone", "weekdays"], "additionalProperties": False},
                     {"properties": {"frequency": {"const": "once"}, "run_at": {"type": "string"}}, "required": ["frequency", "run_at"], "additionalProperties": False},
                 ]},
    "enabled": {"type": "boolean", "description": "Whether scheduled runs are enabled; default true"},
    "end_at": {"type": ["string", "null"], "description": "Optional inclusive end timestamp with timezone offset"},
    "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 7200, "description": "Run timeout; default 1800"},
    "model": {"type": ["string", "null"], "description": "Optional model identifier; null uses managed Codex default"},
    "reasoning_effort": {"type": ["string", "null"], "description": "Optional reasoning effort; null uses managed Codex default"},
}
TOOLS = [
    tool("create_job", "Create a persistent schedule that launches Codex in a selected project, even after this chat closes.", FIELDS, ("name", "project", "prompt", "schedule")),
    tool("update_job", "Update a job. Resume with enabled=true. Queued work is cancelled; an active run keeps its original instructions.", {**JOB_ID, **FIELDS}, ("job_id",)),
    tool("list_jobs", "List all saved schedules, prompts, IDs, and next run times.", {}, readonly=True),
    tool("get_job", "Read a saved job's complete configuration.", JOB_ID, ("job_id",), readonly=True),
    tool("pause_job", "Disable future scheduled runs and cancel queued runs. An active run continues until completion or timeout.", JOB_ID, ("job_id",)),
    tool("run_now", "Queue one immediate run, even for a paused job. Returns quickly; execution starts on the next dispatcher tick, after earlier jobs. Reuses an already queued/active run.", JOB_ID, ("job_id",)),
    tool("get_runs", "Read recent run statuses, final summaries, log paths, and Codex thread IDs. Optionally filter by job_id.", {**JOB_ID, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, readonly=True),
    tool("delete_job", "Delete a paused job and its run records. Refuses while running; log files remain on disk.", JOB_ID, ("job_id",)),
]


def mcp():
    db = connect()
    try:
        for line in sys.stdin:
            request_id = None
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("Request must be a JSON object")
                if "id" not in message:
                    continue
                request_id, method = message["id"], message.get("method")
                params = message.get("params") or {}
                if method == "initialize":
                    version = params.get("protocolVersion")
                    result = {"protocolVersion": version if version in ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25") else "2025-06-18",
                              "capabilities": {"tools": {"listChanged": False}},
                              "serverInfo": {"name": "codex-scheduler", "version": VERSION},
                              "instructions": "Manage server-side Codex routines only when the user requests scheduling. Verify project, timezone, cadence and end date. Runs use fresh chats and workspace-write permissions. run_now queues work; get_runs reads results. Pausing does not interrupt active work. Do not claim a job succeeded merely because it was queued. Scheduled jobs cannot call this scheduler."}
                elif method == "ping":
                    result = {}
                elif method == "tools/list":
                    result = {"tools": TOOLS}
                elif method == "tools/call":
                    try:
                        value = dispatch(db, params.get("name"), params.get("arguments", {}))
                        result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                                  "structuredContent": value, "isError": False}
                    except Exception as error:
                        result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
                else:
                    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}), flush=True)
                    continue
                response = {"jsonrpc": "2.0", "id": request_id, "result": result}
            except Exception as error:
                response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": str(error)}}
            print(json.dumps(response, ensure_ascii=False), flush=True)
    finally:
        db.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mcp", help="serve MCP over stdin/stdout")
    sub.add_parser("tick", help="queue due jobs and execute the oldest pending run")
    call = sub.add_parser("call", help="invoke a tool from the command line")
    call.add_argument("name", choices=[tool["name"] for tool in TOOLS])
    call.add_argument("--arguments", default="{}", help="JSON object; use '-' to read stdin")
    args = parser.parse_args()
    if args.command == "mcp":
        return mcp()
    if args.command == "tick":
        return tick()
    db = connect()
    try:
        raw = sys.stdin.read() if args.arguments == "-" else args.arguments
        print(json.dumps(dispatch(db, args.name, json.loads(raw)), indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
