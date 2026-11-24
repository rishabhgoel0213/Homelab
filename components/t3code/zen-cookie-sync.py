"""Sync signed-in session cookies from macOS Zen Browser to T3 Code's server-browser.

Reads ONLY Zen's cookies.sqlite (plus WAL/SHM sidecars in a private temp copy).
Never reads saved passwords (logins.json / key4.db), history, or macOS Keychain.
"""

import argparse
from collections import Counter
import configparser
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time


DEFAULT_EXCLUDED_DOMAINS = (
    "localhost",
    "127.0.0.1",
    "::1",
    "internal.therealrishabh.com",
    "ts.net",
    "local",
)
MAX_COOKIE_TTL_SECONDS = 400 * 86400
SESSION_COOKIE_TTL_SECONDS = 86400


def _read_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    if path.is_file():
        parser.read(path, encoding="utf-8")
    return parser


def _resolve_profile_path(zen_root: Path, raw_path: str, is_relative: bool) -> Path:
    path = Path(raw_path)
    if is_relative and not path.is_absolute():
        return (zen_root / path).resolve()
    return path.expanduser().resolve()


def find_zen_profile(zen_root: Path, selector: str | None = None) -> Path:
    """Resolve the active Zen Browser profile directory containing cookies.sqlite."""
    if selector:
        direct = Path(selector).expanduser()
        if direct.is_file() and direct.name == "cookies.sqlite":
            return direct.parent.resolve()
        if direct.is_dir() and (direct / "cookies.sqlite").is_file():
            return direct.resolve()
        profiles_dir = zen_root / "Profiles"
        if profiles_dir.is_dir():
            exact = profiles_dir / selector
            if exact.is_dir() and (exact / "cookies.sqlite").is_file():
                return exact.resolve()
            matches = sorted(
                p
                for p in profiles_dir.iterdir()
                if p.is_dir()
                and selector.lower() in p.name.lower()
                and (p / "cookies.sqlite").is_file()
            )
            if matches:
                return matches[0].resolve()
        raise RuntimeError(f"Could not find Zen profile matching {selector!r} under {zen_root}")

    # 1. installs.ini records the currently active default profile per install.
    installs = _read_ini(zen_root / "installs.ini")
    for section in installs.sections():
        default_rel = installs.get(section, "Default", fallback="").strip()
        if default_rel:
            candidate = _resolve_profile_path(zen_root, default_rel, is_relative=True)
            if (candidate / "cookies.sqlite").is_file():
                return candidate

    # 2. profiles.ini Default=1 entries.
    profiles = _read_ini(zen_root / "profiles.ini")
    default_candidates: list[Path] = []
    all_candidates: list[Path] = []
    for section in profiles.sections():
        if not section.startswith("Profile"):
            continue
        raw_path = profiles.get(section, "Path", fallback="").strip()
        if not raw_path:
            continue
        is_rel = profiles.get(section, "IsRelative", fallback="1").strip() != "0"
        candidate = _resolve_profile_path(zen_root, raw_path, is_relative=is_rel)
        if not (candidate / "cookies.sqlite").is_file():
            continue
        all_candidates.append(candidate)
        if profiles.get(section, "Default", fallback="0").strip() == "1":
            default_candidates.append(candidate)

    for group in (default_candidates, all_candidates):
        if group:
            group.sort(key=lambda p: (p / "cookies.sqlite").stat().st_mtime, reverse=True)
            return group[0]

    # 3. Fallback scan under Profiles/.
    profiles_dir = zen_root / "Profiles"
    if profiles_dir.is_dir():
        found = [
            p.resolve()
            for p in profiles_dir.iterdir()
            if p.is_dir() and (p / "cookies.sqlite").is_file()
        ]
        if found:
            found.sort(key=lambda p: (p / "cookies.sqlite").stat().st_mtime, reverse=True)
            return found[0]

    raise RuntimeError(f"No Zen Browser profile with cookies.sqlite found under {zen_root}")


def domain_matches(host: str, pattern: str) -> bool:
    clean_host = host.strip().lstrip(".").lower()
    clean_pat = pattern.strip().lstrip(".").lower()
    if not clean_host or not clean_pat:
        return False
    return clean_host == clean_pat or clean_host.endswith(f".{clean_pat}")


def load_exclude_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    entries: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            entries.append(stripped)
    return entries


def _normalize_same_site(raw_same_site: int | None, secure: bool) -> str:
    if raw_same_site == 2:
        return "Strict"
    if raw_same_site == 0 and secure:
        return "None"
    return "Lax"


def extract_cookies(
    profile_dir: Path,
    *,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    now: float | None = None,
) -> list[dict]:
    """Read active cookies from a safe private copy of Zen's cookies.sqlite."""
    cookies_db = profile_dir / "cookies.sqlite"
    if not cookies_db.is_file():
        raise RuntimeError(f"cookies.sqlite not found in {profile_dir}")

    now_ts = int(time.time() if now is None else now)
    effective_excludes = list(DEFAULT_EXCLUDED_DOMAINS) + list(exclude_domains or [])
    effective_includes = list(include_domains or [])

    with tempfile.TemporaryDirectory(prefix="t3-zen-cookies-") as tmp:
        tmp_dir = Path(tmp)
        os.chmod(tmp_dir, 0o700)
        for suffix in ("", "-wal", "-shm"):
            src = profile_dir / f"cookies.sqlite{suffix}"
            if src.is_file():
                dst = tmp_dir / src.name
                shutil.copy2(src, dst)
                os.chmod(dst, 0o600)

        copy_db = tmp_dir / "cookies.sqlite"
        con = sqlite3.connect(f"file:{copy_db}?mode=ro", uri=True)
        try:
            cols = {
                row[1]
                for row in con.execute("PRAGMA table_info(moz_cookies)").fetchall()
            }
            if not {"name", "value", "host", "path", "expiry"}.issubset(cols):
                raise RuntimeError("Unexpected moz_cookies schema in Zen cookies.sqlite")

            select_cols = [
                "name",
                "value",
                "host",
                "path",
                "expiry",
                "isSecure" if "isSecure" in cols else "0 AS isSecure",
                "isHttpOnly" if "isHttpOnly" in cols else "0 AS isHttpOnly",
                "sameSite" if "sameSite" in cols else "1 AS sameSite",
                "originAttributes" if "originAttributes" in cols else "'' AS originAttributes",
                "lastAccessed" if "lastAccessed" in cols else "0 AS lastAccessed",
            ]
            rows = con.execute(f"SELECT {', '.join(select_cols)} FROM moz_cookies").fetchall()
        finally:
            con.close()

    # Deduplicate by (host_lower, path, name): prefer default container (originAttributes == ""),
    # then newest lastAccessed.
    selected: dict[tuple[str, str, str], tuple[int, int, dict]] = {}

    for (
        name,
        value,
        host,
        path,
        expiry,
        is_secure,
        is_http_only,
        same_site,
        origin_attrs,
        last_accessed,
    ) in rows:
        if not name or not host or value is None:
            continue
        origin_str = str(origin_attrs or "")
        if "privateBrowsingId=" in origin_str or "partitionKey=" in origin_str:
            continue

        host_str = str(host).strip()
        path_str = str(path or "/")
        name_str = str(name)
        value_str = str(value)
        secure = bool(is_secure)
        http_only = bool(is_http_only)

        if any(domain_matches(host_str, pat) for pat in effective_excludes):
            continue
        if effective_includes and not any(
            domain_matches(host_str, pat) for pat in effective_includes
        ):
            continue

        # Firefox stores expiry in seconds since epoch (or milliseconds in rare edge cases).
        try:
            exp_val = int(expiry or 0)
        except (TypeError, ValueError):
            exp_val = 0
        if exp_val > 10_000_000_000:
            exp_val //= 1000
        if exp_val > 0 and exp_val <= now_ts:
            continue

        # Enforce RFC 6265bis cookie prefix rules so Chromium/Playwright accepts them.
        if name_str.startswith("__Host-"):
            if not secure or path_str != "/":
                continue
            host_str = host_str.lstrip(".")
        elif name_str.startswith("__Secure-") and not secure:
            continue

        if exp_val <= 0:
            expires = now_ts + SESSION_COOKIE_TTL_SECONDS
        else:
            expires = min(exp_val, now_ts + MAX_COOKIE_TTL_SECONDS)

        cookie = {
            "name": name_str,
            "value": value_str,
            "domain": host_str,
            "path": path_str,
            "expires": expires,
            "httpOnly": http_only,
            "secure": secure,
            "sameSite": _normalize_same_site(same_site, secure),
        }

        dedup_key = (host_str.lower(), path_str, name_str)
        container_rank = 1 if origin_str == "" else 0
        accessed_rank = int(last_accessed or 0)
        prev = selected.get(dedup_key)
        if prev is None or (container_rank, accessed_rank) > (prev[0], prev[1]):
            selected[dedup_key] = (container_rank, accessed_rank, cookie)

    cookies = [item[2] for item in selected.values()]
    cookies.sort(key=lambda c: (c["domain"].lower(), c["path"], c["name"]))
    return cookies


def compute_cookie_hash(cookies: list[dict]) -> str:
    """Stable SHA-256 fingerprint ignoring expiry bumps and lastAccessed churn."""
    canonical = [
        [
            c["domain"].lower(),
            c["path"],
            c["name"],
            c["value"],
            bool(c["secure"]),
            bool(c["httpOnly"]),
            c["sameSite"],
        ]
        for c in sorted(
            cookies, key=lambda item: (item["domain"].lower(), item["path"], item["name"])
        )
    ]
    encoded = json.dumps(canonical, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_private_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def ssh_command(config: dict, remote_args: list[str]) -> list[str]:
    return [
        config["ssh"],
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        config["sshHost"],
        "--",
        *remote_args,
    ]


def push_cookies(
    config: dict,
    cookies: list[dict],
    *,
    target_profile: str,
    mode: str,
    idle_seconds: int,
) -> dict:
    remote_cmd = [
        config.get("remoteCommand", "t3-browser-cookie-receive"),
        "--profile",
        target_profile,
        "--mode",
        mode,
        "--idle-seconds",
        str(idle_seconds),
    ]
    payload = json.dumps({"schema": 1, "cookies": cookies})
    proc = subprocess.run(
        ssh_command(config, remote_cmd),
        input=payload,
        text=True,
        capture_output=True,
        timeout=150,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.strip() or f"ssh exited with status {proc.returncode}"
        raise RuntimeError(err)
    return json.loads(proc.stdout)


def format_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync signed-in session cookies (never passwords) from Zen Browser to T3 Code."
    )
    parser.add_argument("--config", required=True, help="Path to JSON configuration file")
    parser.add_argument(
        "--background",
        action="store_true",
        help="Continuous background mode: skip unchanged cookies and only apply when T3 browser is idle.",
    )
    parser.add_argument(
        "--domain",
        action="append",
        default=[],
        help="Optional domain suffix filter (repeatable), e.g. --domain google.com",
    )
    parser.add_argument(
        "--exclude-domain",
        action="append",
        default=[],
        help="Extra domain suffix to exclude (repeatable)",
    )
    parser.add_argument(
        "--zen-profile",
        default=None,
        help="Zen profile directory path or name (auto-detected by default)",
    )
    parser.add_argument(
        "--profile",
        default="default",
        help="Target T3 server-browser profile id (default: default)",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Do not refresh a running chrome-headless-shell on nixos-pc",
    )
    parser.add_argument(
        "--idle-seconds",
        type=int,
        default=None,
        help="Minimum T3 browser idle time in seconds for --background mode (default: 600)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect how many cookies/domains would sync without connecting to nixos-pc",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show detected Zen profile and last sync state",
    )
    args = parser.parse_args(argv)

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    zen_root = Path(config["zenRoot"]).expanduser()
    state_dir = Path(config["stateDir"]).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    hash_file = state_dir / "last-hash"
    status_file = state_dir / "last-sync.json"
    exclude_file = state_dir / "exclude-domains.txt"

    if args.status:
        try:
            detected = str(find_zen_profile(zen_root, args.zen_profile))
        except RuntimeError as exc:
            detected = f"unavailable ({exc})"
        last_sync = (
            json.loads(status_file.read_text(encoding="utf-8"))
            if status_file.is_file()
            else None
        )
        print(
            json.dumps(
                {
                    "zenProfile": detected,
                    "excludeFile": str(exclude_file),
                    "lastSync": last_sync,
                },
                indent=2,
            )
        )
        return 0

    lock_path = state_dir / "sync.lock"
    with lock_path.open("w", encoding="utf-8") as lock_handle:
        if args.background:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
        else:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)

        profile_dir = find_zen_profile(zen_root, args.zen_profile)
        excludes = load_exclude_file(exclude_file) + list(args.exclude_domain)
        cookies = extract_cookies(
            profile_dir,
            include_domains=args.domain,
            exclude_domains=excludes,
        )

        domain_counts = Counter(c["domain"].lstrip(".").lower() for c in cookies)
        cookie_hash = compute_cookie_hash(cookies)

        if args.dry_run:
            top_domains = [d for d, _ in domain_counts.most_common(12)]
            print(
                f"Dry run: {len(cookies)} cookies across {len(domain_counts)} domains "
                f"from Zen profile {profile_dir.name}"
            )
            if top_domains:
                print(f"Top domains: {', '.join(top_domains)}")
            return 0

        if not cookies:
            if not args.background:
                print(f"No matching active cookies found in Zen profile {profile_dir.name}.")
            return 0

        is_full_sync = not args.domain and not args.exclude_domain and args.profile == "default"
        if args.background and is_full_sync and hash_file.is_file():
            if hash_file.read_text(encoding="utf-8").strip() == cookie_hash:
                return 0

        idle_seconds = (
            args.idle_seconds
            if args.idle_seconds is not None
            else int(config.get("idleSeconds", 600))
        )
        if args.no_restart:
            mode = "no-restart"
        elif args.background:
            mode = "if-idle"
        else:
            mode = "restart"

        result = push_cookies(
            config,
            cookies,
            target_profile=args.profile,
            mode=mode,
            idle_seconds=idle_seconds,
        )
        status = result.get("status")

        if status == "applied":
            if is_full_sync:
                write_private_file(hash_file, f"{cookie_hash}\n")
                write_private_file(
                    status_file,
                    json.dumps(
                        {
                            "timestamp": format_timestamp(),
                            "status": "applied",
                            "zenProfile": profile_dir.name,
                            "targetProfile": args.profile,
                            "imported": result.get("imported", 0),
                            "skipped": result.get("skipped", 0),
                            "domains": result.get("domains", len(domain_counts)),
                            "restartedBrowser": bool(result.get("restartedBrowser")),
                        },
                        indent=2,
                    )
                    + "\n",
                )
            refreshed = " (browser refreshed)" if result.get("restartedBrowser") else ""
            skipped_note = (
                f", {result['skipped']} skipped" if result.get("skipped") else ""
            )
            print(
                f"[{format_timestamp()}] Synced {result.get('imported', 0)} cookies "
                f"across {result.get('domains', len(domain_counts))} domains from Zen "
                f"({profile_dir.name}) to {config['sshHost']}{refreshed}{skipped_note}."
            )
            return 0

        if status == "deferred-busy":
            reason = result.get("reason", "busy")
            if not args.background:
                print(
                    f"Deferred sync because T3's browser is running ({reason}). "
                    "Re-run without --no-restart to refresh T3's browser immediately."
                )
            return 0

        raise RuntimeError(f"Unexpected response from server: {result}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[{format_timestamp()}] t3-browser-sync: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
