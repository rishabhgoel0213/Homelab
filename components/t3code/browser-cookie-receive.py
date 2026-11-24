"""Receive synced browser cookies over stdin and inject into T3's server-browser profile."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ALLOWED_COOKIE_KEYS = {
    "name",
    "value",
    "domain",
    "path",
    "expires",
    "httpOnly",
    "secure",
    "sameSite",
}
PROFILE_ACTIVITY_ENTRIES = (
    "Cookies",
    "Cookies-journal",
    "Cookies-wal",
    "DIPS",
    "DIPS-wal",
    "History",
    "History-journal",
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnWebGPUCache",
    "Local Storage",
    "Session Storage",
    "Network Persistent State",
)


def validate_profile_id(profile_id: str) -> str:
    if (
        not profile_id
        or profile_id in {".", "..", "incognito"}
        or not PROFILE_ID_RE.fullmatch(profile_id)
    ):
        raise ValueError(f"Invalid T3 browser profile id: {profile_id!r}")
    return profile_id


def version_key(name: str) -> tuple[int, ...]:
    parts = name.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return (-1,)
    return tuple(int(part) for part in parts)


def find_chrome_headless_shell(state_dir: Path) -> Path:
    root = state_dir / "tools" / "chrome-headless-shell"
    candidates: list[tuple[tuple[int, ...], Path]] = []
    if root.is_dir():
        for platform_dir in sorted(root.iterdir()):
            if not platform_dir.is_dir():
                continue
            for version_dir in platform_dir.iterdir():
                if not version_dir.is_dir():
                    continue
                exe = version_dir / "chrome-headless-shell"
                if exe.is_file() and os.access(exe, os.X_OK):
                    candidates.append((version_key(version_dir.name), exe))
    if not candidates:
        raise RuntimeError(
            "T3's chrome-headless-shell is not installed yet; open one tab in T3's browser first."
        )
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _read_proc_cmdline(proc_dir: Path) -> list[str] | None:
    try:
        raw = (proc_dir / "cmdline").read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    return [arg.decode("utf-8", errors="replace") for arg in raw.split(b"\x00") if arg]


def _read_proc_stat(proc_dir: Path) -> tuple[int, int] | None:
    """Return (ppid, utime_plus_stime_ticks) for a /proc/<pid> entry."""
    try:
        text = (proc_dir / "stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    rparen = text.rfind(")")
    if rparen == -1:
        return None
    fields = text[rparen + 2 :].split()
    if len(fields) < 13:
        return None
    try:
        ppid = int(fields[1])
        utime = int(fields[11])
        stime = int(fields[12])
    except ValueError:
        return None
    return ppid, utime + stime


def find_profile_browser_pids(profile_dir: Path, proc_root: Path = Path("/proc")) -> tuple[list[int], list[int]]:
    """Return (main_browser_pids, all_tree_pids) using profile_dir owned by current uid."""
    uid = os.getuid()
    target_flag = f"--user-data-dir={profile_dir}"
    main_pids: list[int] = []
    children_by_ppid: dict[int, list[int]] = {}

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            if entry.stat().st_uid != uid:
                continue
        except OSError:
            continue

        stat = _read_proc_stat(entry)
        if stat is not None:
            ppid, _ = stat
            children_by_ppid.setdefault(ppid, []).append(pid)

        cmdline = _read_proc_cmdline(entry)
        if not cmdline:
            continue
        exe_name = Path(cmdline[0]).name
        if exe_name != "chrome-headless-shell":
            continue
        if target_flag not in cmdline:
            continue
        if any(arg.startswith("--type=") for arg in cmdline[1:]):
            continue
        main_pids.append(pid)

    all_pids: set[int] = set(main_pids)
    queue = list(main_pids)
    while queue:
        parent = queue.pop()
        for child in children_by_ppid.get(parent, ()):
            if child not in all_pids:
                all_pids.add(child)
                queue.append(child)
    return sorted(main_pids), sorted(all_pids)


def profile_idle_seconds(profile_dir: Path, now: float | None = None) -> float:
    now = time.time() if now is None else now
    default_dir = profile_dir / "Default"
    latest_mtime: float | None = None
    for name in PROFILE_ACTIVITY_ENTRIES:
        candidate = default_dir / name
        try:
            st = candidate.stat()
        except OSError:
            continue
        if latest_mtime is None or st.st_mtime > latest_mtime:
            latest_mtime = st.st_mtime
    if latest_mtime is None:
        return float("inf")
    return max(0.0, now - latest_mtime)


def sample_cpu_seconds(pids: list[int], duration: float = 0.5, proc_root: Path = Path("/proc")) -> float:
    if not pids or duration <= 0:
        return 0.0
    clk_tck = float(os.sysconf("SC_CLK_TCK"))

    def total_ticks() -> int:
        total = 0
        for pid in pids:
            stat = _read_proc_stat(proc_root / str(pid))
            if stat is not None:
                total += stat[1]
        return total

    before = total_ticks()
    time.sleep(duration)
    after = total_ticks()
    return max(0.0, (after - before) / clk_tck)


def stop_browser_processes(profile_dir: Path, timeout_seconds: float = 8.0) -> bool:
    main_pids, all_pids = find_profile_browser_pids(profile_dir)
    if not main_pids:
        return False

    for pid in main_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        _, remaining = find_profile_browser_pids(profile_dir)
        if not remaining:
            return True
        time.sleep(0.1)

    _, remaining = find_profile_browser_pids(profile_dir)
    for pid in remaining or all_pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    kill_deadline = time.monotonic() + 2.0
    while time.monotonic() < kill_deadline:
        _, still_alive = find_profile_browser_pids(profile_dir)
        if not still_alive:
            return True
        time.sleep(0.1)

    _, still_alive = find_profile_browser_pids(profile_dir)
    if still_alive:
        raise RuntimeError(
            f"Timed out waiting for chrome-headless-shell PIDs {still_alive} to exit."
        )
    return True


def validate_cookies(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError("Expected JSON payload with schema=1")
    raw_cookies = payload.get("cookies")
    if not isinstance(raw_cookies, list):
        raise ValueError("Expected cookies list in payload")

    cleaned: list[dict] = []
    for item in raw_cookies:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        domain = item.get("domain")
        path = item.get("path")
        if not (
            isinstance(name, str)
            and name
            and isinstance(value, str)
            and isinstance(domain, str)
            and domain
            and isinstance(path, str)
            and path
        ):
            continue
        cookie = {k: v for k, v in item.items() if k in ALLOWED_COOKIE_KEYS}
        cleaned.append(cookie)
    return cleaned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Receive synced cookies on stdin and inject them into T3 Code's server-browser profile."
    )
    parser.add_argument("--state-dir", default="/srv/state/t3code")
    parser.add_argument("--playwright-path", required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--injector", required=True)
    parser.add_argument("--profile", default="default")
    parser.add_argument(
        "--mode",
        choices=("if-idle", "restart", "no-restart"),
        default="if-idle",
    )
    parser.add_argument("--idle-seconds", type=int, default=600)
    args = parser.parse_args(argv)

    profile_id = validate_profile_id(args.profile)
    state_dir = Path(args.state_dir)
    server_browser_dir = state_dir / "userdata" / "server-browser"
    profile_dir = server_browser_dir / "profiles" / profile_id
    server_browser_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    raw_stdin = sys.stdin.read()
    try:
        payload = json.loads(raw_stdin)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON payload on stdin: {exc.msg}") from exc
    cookies = validate_cookies(payload)
    unique_domains = len({c["domain"].lstrip(".").lower() for c in cookies})

    lock_path = server_browser_dir / ".cookie-sync.lock"
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

        main_pids, all_pids = find_profile_browser_pids(profile_dir)
        restarted_browser = False

        if main_pids:
            if args.mode == "no-restart":
                print(
                    json.dumps(
                        {
                            "status": "deferred-busy",
                            "reason": "browser-running",
                            "profile": profile_id,
                            "received": len(cookies),
                            "domains": unique_domains,
                        }
                    )
                )
                return 0

            if args.mode == "if-idle":
                idle = profile_idle_seconds(profile_dir)
                if idle < args.idle_seconds:
                    print(
                        json.dumps(
                            {
                                "status": "deferred-busy",
                                "reason": "recent-activity",
                                "idleSeconds": round(idle, 1),
                                "profile": profile_id,
                                "received": len(cookies),
                                "domains": unique_domains,
                            }
                        )
                    )
                    return 0

                cpu_delta = sample_cpu_seconds(all_pids, duration=0.5)
                if cpu_delta > 0.05:
                    print(
                        json.dumps(
                            {
                                "status": "deferred-busy",
                                "reason": "active-cpu",
                                "cpuDeltaSeconds": round(cpu_delta, 3),
                                "profile": profile_id,
                                "received": len(cookies),
                                "domains": unique_domains,
                            }
                        )
                    )
                    return 0

            restarted_browser = stop_browser_processes(profile_dir)

        executable_path = find_chrome_headless_shell(state_dir)
        inject_input = json.dumps(
            {
                "profileDir": str(profile_dir),
                "executablePath": str(executable_path),
                "playwrightPath": args.playwright_path,
                "cookies": cookies,
            }
        )
        proc = subprocess.run(
            [args.node, args.injector],
            input=inject_input,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr.strip() or f"injector exited with status {proc.returncode}"
            raise RuntimeError(err)

        result = json.loads(proc.stdout)
        print(
            json.dumps(
                {
                    "status": "applied",
                    "profile": profile_id,
                    "received": len(cookies),
                    "imported": int(result.get("imported", 0)),
                    "skipped": int(result.get("skipped", 0)),
                    "skippedDomains": result.get("skippedDomains", []),
                    "domains": unique_domains,
                    "restartedBrowser": restarted_browser,
                }
            )
        )
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"t3-browser-cookie-receive: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
