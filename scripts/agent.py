#!/usr/bin/env python3
"""Inspect conversation metadata and manage disposable agent work directories."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


SESSION_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SLUG_RE = re.compile(r"[^a-z0-9]+")


def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


def paths() -> tuple[Path, Path, Path, Path]:
    state_root = env_path("AGENT_STATE_ROOT", "/srv/state/agents")
    work_root = env_path("AGENT_WORK_ROOT", "/var/tmp/agent-work")
    codex_home = env_path("CODEX_HOME", "/srv/state/codex")
    return state_root, work_root, codex_home, state_root / "index.jsonl"


def now_utc() -> datetime:
    return datetime.now(UTC)


def isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def atomic_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_native_titles(codex_home: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    native_index = codex_home / "session_index.jsonl"
    if not native_index.is_file():
        return result
    with native_index.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            session_id = record.get("id")
            if isinstance(session_id, str):
                result[session_id] = {
                    "title": str(record.get("thread_name") or session_id),
                    "updated_at": str(record.get("updated_at") or ""),
                }
    return result


def read_session_metadata(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle):
                if line_number >= 128:
                    break
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "session_meta" and isinstance(record.get("payload"), dict):
                    return record["payload"]
    except OSError:
        pass
    return {}


def discover_codex_sessions(codex_home: Path) -> list[dict[str, Any]]:
    titles = load_native_titles(codex_home)
    sessions: dict[str, dict[str, Any]] = {}
    roots = (
        ("active", codex_home / "sessions"),
        ("archived", codex_home / "archived_sessions"),
    )
    for status, root in roots:
        if not root.is_dir():
            continue
        for session_path in root.glob("**/*.jsonl"):
            match = SESSION_ID_RE.search(session_path.name)
            metadata = read_session_metadata(session_path)
            session_id = metadata.get("id") or (match.group(0) if match else None)
            if not isinstance(session_id, str):
                continue
            stat = session_path.stat()
            fallback_time = isoformat(datetime.fromtimestamp(stat.st_mtime, UTC))
            title_record = titles.get(session_id, {})
            candidate = {
                "schema": 1,
                "id": session_id,
                "harness": "codex",
                "title": title_record.get("title") or session_id,
                "cwd": str(metadata.get("cwd") or ""),
                "native_session": str(session_path),
                "created_at": str(metadata.get("timestamp") or fallback_time),
                "updated_at": title_record.get("updated_at") or fallback_time,
                "status": status,
                "source": str(metadata.get("source") or ""),
            }
            previous = sessions.get(session_id)
            if previous is None or candidate["status"] == "active" or candidate["updated_at"] > previous["updated_at"]:
                sessions[session_id] = candidate
    return sorted(sessions.values(), key=lambda item: item["updated_at"], reverse=True)


def build_index(quiet: bool = False) -> list[dict[str, Any]]:
    _, _, codex_home, index_path = paths()
    records = discover_codex_sessions(codex_home)
    atomic_jsonl(index_path, records)
    if not quiet:
        print(f"Indexed {len(records)} Codex conversations in {index_path}.")
    return records


def load_index(refresh: bool = True) -> list[dict[str, Any]]:
    _, _, _, index_path = paths()
    if refresh or not index_path.is_file():
        return build_index(quiet=True)
    result = []
    with index_path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return result


def safe_slug(raw: str) -> str:
    value = SLUG_RE.sub("-", raw.lower()).strip("-")
    if not value:
        raise ValueError("the task name must contain a letter or number")
    return value[:64]


def manifest_path(work_dir: Path) -> Path:
    return work_dir / ".agent-work.json"


def write_manifest(work_dir: Path, manifest: dict[str, Any]) -> None:
    target = manifest_path(work_dir)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".manifest.", dir=work_dir)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.chmod(0o600)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def read_manifest(work_dir: Path) -> dict[str, Any] | None:
    try:
        with manifest_path(work_dir).open(encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def resolve_managed_work_dir(raw: str) -> Path:
    _, work_root, _, _ = paths()
    candidate = Path(raw).expanduser().resolve()
    root = work_root.resolve()
    if candidate.parent != root or not candidate.is_dir() or candidate.is_symlink():
        raise ValueError(f"not a direct managed work directory beneath {root}: {candidate}")
    if read_manifest(candidate) is None:
        raise ValueError(f"missing or invalid {manifest_path(candidate)}")
    return candidate


def directory_size(path: Path) -> int:
    total = 0
    for root, directories, files in os.walk(path, followlinks=False):
        directories[:] = [name for name in directories if not (Path(root) / name).is_symlink()]
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                continue
    return total


def human_size(size: int) -> str:
    value = float(size)
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or suffix == "TiB":
            return f"{value:.1f}{suffix}" if suffix != "B" else f"{int(value)}B"
        value /= 1024
    return f"{size}B"


def command_index(args: argparse.Namespace) -> int:
    build_index(quiet=args.quiet)
    return 0


def command_history(args: argparse.Namespace) -> int:
    records = load_index(refresh=not args.no_refresh)[: args.limit]
    print("UPDATED              STATUS    HARNESS  TITLE                                                        ID")
    for record in records:
        updated = str(record.get("updated_at", ""))[:19]
        title = str(record.get("title", "")).replace("\n", " ")[:60]
        print(
            f"{updated:<20} {str(record.get('status', '')):<9} "
            f"{str(record.get('harness', '')):<8} {title:<60} {record.get('id', '')}"
        )
    return 0


def command_show(args: argparse.Namespace) -> int:
    matches = [record for record in load_index(refresh=not args.no_refresh) if record.get("id") == args.id]
    if not matches:
        print(f"Conversation not found: {args.id}", file=sys.stderr)
        return 1
    print(json.dumps(matches[0], indent=2, sort_keys=True))
    return 0


def command_new(args: argparse.Namespace) -> int:
    _, work_root, _, _ = paths()
    if args.ttl <= 0:
        raise ValueError("--ttl must be greater than zero")
    ensure_private_directory(work_root)
    created = now_utc()
    identifier = str(uuid.uuid4())
    name = f"{created.date().isoformat()}-{safe_slug(args.name)}-{identifier[:8]}"
    work_dir = work_root / name
    work_dir.mkdir(mode=0o700)
    manifest = {
        "schema": 1,
        "id": identifier,
        "name": args.name,
        "harness": args.harness,
        "conversation_id": args.conversation or "",
        "created_at": isoformat(created),
        "expires_at": isoformat(created + timedelta(days=args.ttl)),
        "retention": "expire",
    }
    write_manifest(work_dir, manifest)
    print(work_dir)
    return 0


def command_keep(args: argparse.Namespace) -> int:
    work_dir = resolve_managed_work_dir(args.path)
    manifest = read_manifest(work_dir) or {}
    manifest["retention"] = "keep"
    manifest["expires_at"] = None
    write_manifest(work_dir, manifest)
    print(f"Keeping {work_dir} until explicitly released.")
    return 0


def command_release(args: argparse.Namespace) -> int:
    if args.days <= 0:
        raise ValueError("--days must be greater than zero")
    work_dir = resolve_managed_work_dir(args.path)
    manifest = read_manifest(work_dir) or {}
    manifest["retention"] = "expire"
    manifest["expires_at"] = isoformat(now_utc() + timedelta(days=args.days))
    write_manifest(work_dir, manifest)
    print(f"{work_dir} will expire at {manifest['expires_at']}.")
    return 0


def command_work(_args: argparse.Namespace) -> int:
    _, work_root, _, _ = paths()
    ensure_private_directory(work_root)
    print("RETENTION  EXPIRES               SIZE       PATH")
    for entry in sorted(work_root.iterdir()):
        if not entry.is_dir() or entry.is_symlink():
            print(f"unmanaged  -                     -          {entry}")
            continue
        manifest = read_manifest(entry)
        if manifest is None:
            print(f"unmanaged  -                     {human_size(directory_size(entry)):<10} {entry}")
            continue
        expires = str(manifest.get("expires_at") or "-")[:20]
        retention = str(manifest.get("retention") or "expire")
        print(f"{retention:<10} {expires:<21} {human_size(directory_size(entry)):<10} {entry}")
    return 0


def command_gc(args: argparse.Namespace) -> int:
    _, work_root, _, _ = paths()
    ensure_private_directory(work_root)
    current_time = now_utc()
    deleted = 0
    reclaimable = 0
    for entry in sorted(work_root.iterdir()):
        if not entry.is_dir() or entry.is_symlink():
            continue
        manifest = read_manifest(entry)
        if manifest is None or manifest.get("retention") == "keep":
            continue
        expires_at = manifest.get("expires_at")
        if not isinstance(expires_at, str):
            continue
        try:
            expired = parse_time(expires_at) <= current_time
        except ValueError:
            continue
        if not expired:
            continue
        size = directory_size(entry)
        reclaimable += size
        action = "delete" if args.apply else "would-delete"
        if not args.quiet:
            print(f"{action} {human_size(size):>10} {entry}")
        if args.apply:
            shutil.rmtree(entry)
            deleted += 1
    if not args.quiet:
        if args.apply:
            print(f"Deleted {deleted} expired work directories; reclaimed {human_size(reclaimable)}.")
        else:
            print(f"Dry run; {human_size(reclaimable)} is eligible. Pass --apply to delete it.")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="agent", description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    index = commands.add_parser("index", help="rebuild the metadata-only conversation index")
    index.add_argument("--quiet", action="store_true")
    index.set_defaults(func=command_index)

    history = commands.add_parser("history", help="list recent conversations")
    history.add_argument("--limit", type=int, default=30)
    history.add_argument("--no-refresh", action="store_true")
    history.set_defaults(func=command_history)

    show = commands.add_parser("show", help="show one conversation's metadata")
    show.add_argument("id")
    show.add_argument("--no-refresh", action="store_true")
    show.set_defaults(func=command_show)

    new = commands.add_parser("new", help="create an expiring isolated work directory")
    new.add_argument("name")
    new.add_argument("--ttl", type=int, default=int(os.environ.get("AGENT_WORK_TTL_DAYS", "30")))
    new.add_argument("--harness", default=os.environ.get("AGENT_HARNESS", "unknown"))
    new.add_argument("--conversation")
    new.set_defaults(func=command_new)

    work = commands.add_parser("work", help="list managed and unmanaged task work")
    work.set_defaults(func=command_work)

    keep = commands.add_parser("keep", help="retain a managed work directory")
    keep.add_argument("path")
    keep.set_defaults(func=command_keep)

    release = commands.add_parser("release", help="make retained work expire again")
    release.add_argument("path")
    release.add_argument("--days", type=int, default=30)
    release.set_defaults(func=command_release)

    gc = commands.add_parser("gc", help="remove expired managed work directories")
    gc.add_argument("--apply", action="store_true")
    gc.add_argument("--quiet", action="store_true")
    gc.set_defaults(func=command_gc)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        return int(args.func(args))
    except (OSError, ValueError) as error:
        print(f"agent: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
