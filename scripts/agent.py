#!/usr/bin/env python3
"""Manage disposable agent work directories and temporary internal sites."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


SESSION_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SLUG_RE = re.compile(r"[^a-z0-9]+")
SITE_TTL_RE = re.compile(r"^(\d+)([mhd])$")


def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


def paths() -> tuple[Path, Path]:
    state_root = env_path("AGENT_STATE_ROOT", "/srv/state/agents")
    work_root = env_path("AGENT_WORK_ROOT", "/var/tmp/agent-work")
    return state_root, work_root


def site_paths() -> tuple[Path, str]:
    state_root, _ = paths()
    registry = env_path("AGENT_SITE_REGISTRY", str(state_root / "sites.json"))
    domain = os.environ.get("AGENT_SITE_DOMAIN", "internal.therealrishabh.com").strip(".")
    return registry, domain


def now_utc() -> datetime:
    return datetime.now(UTC)


def isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def copy_agent_policy_files(work_dir: Path) -> int:
    policy_root = env_path("AGENT_POLICY_ROOT", "/etc/agents")
    if not policy_root.is_dir():
        raise ValueError(f"agent policy root does not exist: {policy_root}")
    policy_files = sorted(
        path for path in policy_root.iterdir() if path.is_file() and path.suffix.lower() == ".md"
    )
    if not policy_files:
        raise ValueError(f"agent policy root contains no Markdown files: {policy_root}")

    copied = 0
    for source in policy_files:
        target = work_dir / source.name
        if target.exists() or target.is_symlink():
            continue
        shutil.copyfile(source, target)
        target.chmod(0o644)
        copied += 1
    return copied


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
    _, work_root = paths()
    candidate = Path(raw).expanduser().resolve()
    root = work_root.resolve()
    if candidate.parent != root or not candidate.is_dir() or candidate.is_symlink():
        raise ValueError(f"not a direct managed work directory beneath {root}: {candidate}")
    if read_manifest(candidate) is None:
        raise ValueError(f"missing or invalid {manifest_path(candidate)}")
    return candidate


def current_managed_work_dir() -> Path:
    _, work_root = paths()
    root = work_root.resolve()
    current = Path.cwd().resolve()
    try:
        relative = current.relative_to(root)
    except ValueError as error:
        raise ValueError(f"run this command inside a managed work directory beneath {root}") from error
    if not relative.parts:
        raise ValueError(f"run this command inside a managed work directory beneath {root}")
    return resolve_managed_work_dir(str(root / relative.parts[0]))


def parse_site_ttl(value: str) -> timedelta:
    match = SITE_TTL_RE.fullmatch(value.lower())
    if match is None:
        raise ValueError("--ttl must use an integer followed by m, h, or d (for example, 30m or 4h)")
    amount = int(match.group(1))
    unit = match.group(2)
    seconds = amount * {"m": 60, "h": 3600, "d": 86400}[unit]
    if seconds < 300 or seconds > 7 * 86400:
        raise ValueError("--ttl must be between 5m and 7d")
    return timedelta(seconds=seconds)


def load_site_registry(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid temporary-site registry: {path}") from error
    sites = value.get("sites") if isinstance(value, dict) else None
    if not isinstance(sites, list):
        raise ValueError(f"invalid temporary-site registry: {path}")
    return [site for site in sites if isinstance(site, dict)]


def valid_site_entries(entries: list[dict[str, Any]], current_time: datetime) -> list[dict[str, Any]]:
    _, work_root = paths()
    root = work_root.resolve()
    valid = []
    for entry in entries:
        expires_at = entry.get("expires_at")
        work_dir_raw = entry.get("work_dir")
        task_id = entry.get("task_id")
        if not isinstance(expires_at, str) or not isinstance(work_dir_raw, str) or not isinstance(task_id, str):
            continue
        try:
            if parse_time(expires_at) <= current_time:
                continue
            untrusted_work_dir = Path(work_dir_raw)
            if untrusted_work_dir.is_symlink():
                continue
            work_dir = untrusted_work_dir.resolve()
        except (OSError, ValueError):
            continue
        if work_dir.parent != root or not work_dir.is_dir():
            continue
        manifest = read_manifest(work_dir)
        if manifest is None or manifest.get("id") != task_id:
            continue
        valid.append(entry)
    return valid


class SiteRegistryLock:
    def __init__(self, registry: Path):
        self.path = registry.with_suffix(registry.suffix + ".lock")
        self.handle: Any = None

    def __enter__(self) -> "SiteRegistryLock":
        ensure_private_directory(self.path.parent)
        self.handle = self.path.open("a+")
        self.path.chmod(0o600)
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *_args: Any) -> None:
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def write_site_registry(path: Path, entries: list[dict[str, Any]]) -> None:
    atomic_json(path, {"schema": 1, "sites": entries})


def command_site_expose(args: argparse.Namespace) -> int:
    if args.port <= 0 or args.port > 65535:
        raise ValueError("port must be between 1 and 65535")
    ttl = parse_site_ttl(args.ttl)
    work_dir = current_managed_work_dir()
    manifest = read_manifest(work_dir) or {}
    task_id = manifest.get("id")
    if not isinstance(task_id, str) or SESSION_ID_RE.fullmatch(task_id) is None:
        raise ValueError(f"managed work manifest has no valid id: {manifest_path(work_dir)}")
    try:
        with socket.create_connection(("127.0.0.1", args.port), timeout=1):
            pass
    except OSError as error:
        raise ValueError(f"nothing is accepting connections on 127.0.0.1:{args.port}") from error

    registry, domain = site_paths()
    site_name = safe_slug(args.name)[:32]
    host = f"task-{site_name}-{task_id[:8]}.{domain}"
    created = now_utc()
    entry = {
        "schema": 1,
        "name": site_name,
        "host": host,
        "port": args.port,
        "task_id": task_id,
        "work_dir": str(work_dir),
        "created_at": isoformat(created),
        "expires_at": isoformat(created + ttl),
    }
    with SiteRegistryLock(registry):
        entries = valid_site_entries(load_site_registry(registry), created)
        entries = [existing for existing in entries if existing.get("host") != host]
        entries.append(entry)
        write_site_registry(registry, entries)
    print(f"https://{host}")
    return 0


def command_site_list(_args: argparse.Namespace) -> int:
    registry, _ = site_paths()
    with SiteRegistryLock(registry):
        entries = valid_site_entries(load_site_registry(registry), now_utc())
        write_site_registry(registry, entries)
    print("EXPIRES               PORT   HOST")
    for entry in sorted(entries, key=lambda item: str(item.get("expires_at"))):
        print(f"{str(entry.get('expires_at'))[:20]:<21} {entry.get('port')!s:<6} {entry.get('host')}")
    return 0


def command_site_stop(args: argparse.Namespace) -> int:
    work_dir = current_managed_work_dir()
    manifest = read_manifest(work_dir) or {}
    task_id = manifest.get("id")
    registry, domain = site_paths()
    target = args.site.removeprefix("https://").rstrip("/")
    if "." not in target:
        target = f"task-{safe_slug(target)[:32]}-{str(task_id)[:8]}.{domain}"
    with SiteRegistryLock(registry):
        entries = valid_site_entries(load_site_registry(registry), now_utc())
        remaining = [
            entry
            for entry in entries
            if not (entry.get("host") == target and entry.get("task_id") == task_id)
        ]
        if len(remaining) == len(entries):
            raise ValueError(f"no temporary site named {args.site!r} belongs to this task")
        write_site_registry(registry, remaining)
    print(f"Stopped https://{target}")
    return 0


def command_site_prune(args: argparse.Namespace) -> int:
    registry, _ = site_paths()
    with SiteRegistryLock(registry):
        entries = load_site_registry(registry)
        valid = valid_site_entries(entries, now_utc())
        write_site_registry(registry, valid)
    if not args.quiet:
        print(f"Removed {len(entries) - len(valid)} expired or orphaned temporary site registrations.")
    return 0


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


def command_new(args: argparse.Namespace) -> int:
    _, work_root = paths()
    if args.ttl <= 0:
        raise ValueError("--ttl must be greater than zero")
    ensure_private_directory(work_root)
    created = now_utc()
    identifier = str(uuid.uuid4())
    name = f"{created.date().isoformat()}-{safe_slug(args.name)}-{identifier[:8]}"
    work_dir = work_root / name
    work_dir.mkdir(mode=0o700)
    try:
        copy_agent_policy_files(work_dir)
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
    except (OSError, ValueError):
        shutil.rmtree(work_dir)
        raise
    print(work_dir)
    return 0


def command_policy_sync(args: argparse.Namespace) -> int:
    _, work_root = paths()
    ensure_private_directory(work_root)
    directories = 0
    copied = 0
    for entry in sorted(work_root.iterdir()):
        if not entry.is_dir() or entry.is_symlink() or read_manifest(entry) is None:
            continue
        directories += 1
        copied += copy_agent_policy_files(entry)
    if not args.quiet:
        print(f"Copied {copied} missing policy files across {directories} managed work directories.")
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
    _, work_root = paths()
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
    _, work_root = paths()
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

    site = commands.add_parser("site", help="publish short-lived task-local web servers")
    site_commands = site.add_subparsers(dest="site_command", required=True)

    site_expose = site_commands.add_parser("expose", help="publish a loopback port on a temporary internal URL")
    site_expose.add_argument("port", type=int)
    site_expose.add_argument("--name", default="preview")
    site_expose.add_argument("--ttl", default="4h")
    site_expose.set_defaults(func=command_site_expose)

    site_list = site_commands.add_parser("list", help="list active temporary internal URLs")
    site_list.set_defaults(func=command_site_list)

    site_stop = site_commands.add_parser("stop", help="remove one temporary internal URL")
    site_stop.add_argument("site", help="site name, hostname, or URL")
    site_stop.set_defaults(func=command_site_stop)

    site_prune = site_commands.add_parser("prune", help="remove expired and orphaned temporary URLs")
    site_prune.add_argument("--quiet", action="store_true")
    site_prune.set_defaults(func=command_site_prune)

    new = commands.add_parser("new", help="create an expiring isolated work directory")
    new.add_argument("name")
    new.add_argument("--ttl", type=int, default=int(os.environ.get("AGENT_WORK_TTL_DAYS", "30")))
    new.add_argument("--harness", default=os.environ.get("AGENT_HARNESS", "unknown"))
    new.add_argument("--conversation")
    new.set_defaults(func=command_new)

    work = commands.add_parser("work", help="list managed and unmanaged task work")
    work.set_defaults(func=command_work)

    policy_sync = commands.add_parser(
        "policy-sync", help="copy missing canonical policy files into managed work directories"
    )
    policy_sync.add_argument("--quiet", action="store_true")
    policy_sync.set_defaults(func=command_policy_sync)

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
