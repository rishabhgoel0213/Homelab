"""Backend-independent focus profiles. Enforcement belongs to the backend."""

import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time


class Error(Exception):
    pass


def run(argv, json_output=False):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Error(f"Command unavailable or timed out: {argv[0]}: {exc}") from exc
    if result.returncode:
        raise Error(
            result.stderr.strip()
            or result.stdout.strip()
            or f"Command failed: {argv[0]}"
        )
    if json_output:
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            raise Error(
                "Backend returned invalid JSON; session state is unknown"
            ) from exc
    return result.stdout.strip()


def load_config(path):
    config = json.loads(Path(path).read_text())
    if set(config) - {"version", "backend", "profiles"} or config.get("version") != 1:
        raise Error("Unsupported configuration schema")
    if config.get("backend") not in BACKENDS:
        raise Error("Unsupported backend; no restrictions have been weakened")
    if not isinstance(config.get("profiles"), dict) or not config["profiles"]:
        raise Error("At least one profile is required")
    for name, p in config["profiles"].items():
        if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
            raise Error("Profile IDs must be lowercase letters, digits and hyphens")
        if set(p) - {
            "label",
            "minutes",
            "locked",
            "blocked_apps",
            "blocked_sites",
            "launch_apps",
            "launch_urls",
        }:
            raise Error(f"{name}: unsupported profile setting")
        if (
            not isinstance(p.get("label"), str)
            or not p["label"]
            or re.search(r"[\n\r|]", p["label"])
        ):
            raise Error(f"{name}: invalid label")
        if type(p.get("minutes")) is not int or not 1 <= p["minutes"] <= 1440:
            raise Error(f"{name}: minutes must be 1..1440")
        if type(p.get("locked")) is not bool:
            raise Error(f"{name}: locked must be a boolean")
        for key in ("blocked_apps", "blocked_sites", "launch_apps", "launch_urls"):
            if not isinstance(p.get(key), list) or not all(
                isinstance(x, str) for x in p[key]
            ):
                raise Error(f"{name}: {key} must be a list of strings")
        for app in p["blocked_apps"] + p["launch_apps"]:
            if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", app):
                raise Error(f"{name}: use app bundle identifiers: {app}")
        for site in p["blocked_sites"]:
            if len(site) > 253 or not re.fullmatch(
                r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
                site,
            ):
                raise Error(
                    f"{name}: use lowercase hostnames, without paths or wildcards: {site}"
                )
        for url in p["launch_urls"]:
            if not re.match(r"https?://[^/\s]+", url) or any(c.isspace() for c in url):
                raise Error(f"{name}: launch URLs must be http(s) URLs")
    return config


class Abstand:
    """The only vendor-specific CLI and JSON knowledge lives here."""

    def __init__(self):
        self.binary = os.environ.get(
            "WORKMODE_ABSTAND",
            "/Applications/Nix Background Apps/Abstand.app/Contents/MacOS/Abstand",
        )

    def call(self, *args, json_output=True):
        return run([self.binary, *map(str, args)], json_output)

    def status(self):
        status = self.call("status")
        if status.get("version") != "v0.1.35p" or not isinstance(
            status.get("sessions"), list
        ):
            raise Error(
                "Unexpected Abstand version/schema; update the adapter before starting sessions"
            )
        return status["sessions"]

    def ready(self):
        try:
            self.status()
        except Error:
            self.call("app", "start", json_output=False)
            for _ in range(15):
                time.sleep(0.5)
                try:
                    self.status()
                    return
                except Error:
                    pass
            raise Error(
                "Abstand is not ready. Open it and complete its macOS permission setup."
            )

    def open(self):
        self.ready()
        self.call("app", "start", json_output=False)

    def setup(self):
        self.ready()
        self.call("recovery-agent", "install", json_output=False)
        self.check_recovery()

    def check_recovery(self):
        result = self.call("recovery-agent", "status", json_output=False)
        if "enabled: true" not in result.splitlines():
            raise Error(
                "Recovery agent is not enabled. Run workmode setup before locked sessions."
            )

    def intentions(self):
        return self.call("intention", "list")

    @staticmethod
    def matches(item, p):
        b = item["behavior"]
        rules = [(c["transition"], c["rule"]) for c in item["conditions"]]
        return (
            b["type"] == "block"
            and b["scope"] == "blockTargets"
            and b["enforcementMode"] == ("strict" if p["locked"] else "casual")
            and item["pausedAt"] is None
            and sorted((x["action"], x["app"]["bundleId"]) for x in b["appTargets"])
            == sorted(("block", a) for a in set(p["blocked_apps"]))
            and sorted(
                (x["action"], x["website"]["hostname"], x.get("path"))
                for x in b["websiteTargets"]
            )
            == sorted(("block", s, None) for s in set(p["blocked_sites"]))
            and len(rules) == 2
            and ("start", {"type": "manual"}) in rules
            and (
                "end",
                {
                    "type": "afterTransition",
                    "anchorTransition": "start",
                    "offsetMs": p["minutes"] * 60000,
                },
            )
            in rules
        )

    def prepare(self, name, p):
        fingerprint = hashlib.sha256(
            json.dumps(p, sort_keys=True).encode()
        ).hexdigest()[:16]
        title = f"Workmode/{name}/{fingerprint}"
        matches = [
            i for i in self.intentions() if i["name"] == title and self.matches(i, p)
        ]
        if matches:
            return matches[0]["id"]
        args = [
            "intention",
            "create",
            "--name",
            title,
            "--duration",
            f"{p['minutes']}m",
            "--mode",
            "strict" if p["locked"] else "casual",
            "--scope",
            "block",
        ]
        for app in sorted(set(p["blocked_apps"])):
            args.extend(["--block-app", app])
        for site in sorted(set(p["blocked_sites"])):
            args.extend(["--block-site", site])
        # Never retry a mutation blindly: a timeout may follow a successful write.
        try:
            created = self.call(*args)
        except Error:
            recovered = [
                i
                for i in self.intentions()
                if i["name"] == title and self.matches(i, p)
            ]
            if not recovered:
                raise
            created = recovered[0]
        if not self.matches(created, p):
            raise Error("Backend did not preserve the requested restrictions")
        return created["id"]

    def start(self, intention_id):
        try:
            self.call("intention", "start", intention_id)
        except Error:
            if not any(s["intentionId"] == intention_id for s in self.status()):
                raise
        if not any(s["intentionId"] == intention_id for s in self.status()):
            raise Error("Backend did not confirm the session started")

    def stop(self, intention_id):
        self.call("intention", "stop", intention_id)
        if any(s["intentionId"] == intention_id for s in self.status()):
            raise Error("Backend still reports the session active")

    def sessions(self):
        sessions = self.status()
        if not sessions:
            return []
        intentions = {i["id"]: i for i in self.intentions()}
        result = []
        for session in sessions:
            item = intentions[session["intentionId"]]
            rules = [
                c["rule"]
                for c in item["conditions"]
                if c["transition"] == "end"
                and c["rule"]["type"] == "afterTransition"
                and c["rule"]["anchorTransition"] == "start"
            ]
            end = (
                session["startedAt"] + rules[0]["offsetMs"] if len(rules) == 1 else None
            )
            result.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "locked": item["behavior"].get("enforcementMode") != "casual",
                    "ends_at_ms": end,
                }
            )
        return result


BACKENDS = {"abstand": Abstand}


@contextlib.contextmanager
def mutex():
    directory = Path(
        os.environ.get(
            "WORKMODE_STATE", str(Path.home() / "Library/Application Support/Workmode")
        )
    )
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "command.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield directory


def guard_backend(directory, backend):
    marker = directory / "backend"
    if marker.exists() and marker.read_text() != backend:
        old = marker.read_text()
        if old not in BACKENDS or BACKENDS[old]().sessions():
            raise Error(
                "Previous backend has an active or unverifiable session; finish it before switching"
            )
    marker.write_text(backend)


def start(config, name, backend):
    p = config["profiles"].get(name)
    if p is None:
        raise Error(f"Unknown profile: {name}")
    if not p["blocked_apps"] and not p["blocked_sites"]:
        raise Error("This profile needs a blocklist before it can start")
    backend.ready()
    if backend.sessions():
        raise Error(
            "A session is already active. Finish it before starting another profile."
        )
    if p["locked"]:
        backend.check_recovery()
    intention_id = backend.prepare(name, p)
    backend.start(intention_id)
    failures = []
    for args in [["/usr/bin/open", "-b", a] for a in p["launch_apps"]] + [
        ["/usr/bin/open", u] for u in p["launch_urls"]
    ]:
        try:
            run(args)
        except Error as exc:
            failures.append(str(exc))
    if failures:
        raise Error(
            "Session IS ACTIVE, but a work app/page failed to open: "
            + "; ".join(failures)
        )
    return f"Started {p['label']} for {p['minutes']} minutes"


def clean(text):
    return str(text).replace("|", "/").replace("\n", " ").replace("\r", " ")


def menu(config, backend, command):
    try:
        sessions = backend.sessions()
    except (Error, KeyError, TypeError) as exc:
        return "\n".join(
            [
                "Workmode !",
                "---",
                clean(exc),
                f"Set up / open blocker | bash={command} param1=setup terminal=false refresh=true",
            ]
        )
    lines = ["Workmode", "---"]
    if sessions:
        s = sessions[0]
        remaining = (
            max(0, math.ceil((s["ends_at_ms"] / 1000 - time.time()) / 60))
            if s["ends_at_ms"]
            else None
        )
        clock = f"{remaining}m" if remaining is not None else "active"
        if remaining == 0:
            clock = "finishing"
        lines[0] = f"Workmode {clock} {'🔒' if s['locked'] else ''}"
        for s in sessions:
            parts = s["name"].split("/")
            label = (
                config["profiles"].get(parts[1], {}).get("label", parts[1])
                if len(parts) == 3 and parts[0] == "Workmode"
                else s["name"]
            )
            lines.append(clean(label))
        if (
            len(sessions) == 1
            and not sessions[0]["locked"]
            and sessions[0]["name"].startswith("Workmode/")
        ):
            lines.append(
                f"End session | bash={command} param1=stop terminal=false refresh=true"
            )
        else:
            lines.append("Locked until the session ends")
    else:
        for name, p in config["profiles"].items():
            if not p["blocked_apps"] and not p["blocked_sites"]:
                lines.append(f"{p['label']} — needs blocklist | color=gray")
            else:
                lines.append(
                    f"{p['label']} — {p['minutes']}m{' 🔒' if p['locked'] else ''} | bash={command} param1=start param2={name} terminal=false refresh=true"
                )
    lines.extend(
        [
            "---",
            f"Open blocker | bash={command} param1=open terminal=false",
            f"Check setup | bash={command} param1=doctor terminal=true",
            "Refresh | refresh=true",
        ]
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=os.environ.get("WORKMODE_CONFIG", "/etc/workmode/profiles.json"),
    )
    parser.add_argument(
        "action",
        choices=[
            "validate",
            "list",
            "setup",
            "doctor",
            "start",
            "stop",
            "status",
            "menu",
            "open",
        ],
    )
    parser.add_argument("profile", nargs="?")
    args = parser.parse_args()
    config = load_config(args.config)
    backend = BACKENDS[config["backend"]]()
    if args.action == "validate":
        print("Configuration valid; empty blocklists remain disabled")
    elif args.action == "list":
        print(json.dumps(config["profiles"], indent=2))
    elif args.action == "menu":
        print(
            menu(
                config,
                backend,
                os.environ.get(
                    "WORKMODE_COMMAND", "/run/current-system/sw/bin/workmode"
                ),
            )
        )
    elif args.action == "status":
        print(
            json.dumps(
                {"backend": config["backend"], "sessions": backend.sessions()}, indent=2
            )
        )
    elif args.action == "doctor":
        print(
            json.dumps(
                {"backend": config["backend"], "sessions": backend.sessions()}, indent=2
            )
        )
        backend.check_recovery()
        print(
            "Recovery agent enabled. Verify Abstand Accessibility permission and a short app/site block on this Mac before relying on enforcement."
        )
    elif args.action == "open":
        backend.open()
    else:
        with mutex() as directory:
            guard_backend(directory, config["backend"])
            if args.action == "setup":
                backend.setup()
                print(
                    "Abstand ready; recovery enabled. Grant Abstand Accessibility permission in System Settings, then test blocking."
                )
            elif args.action == "start":
                print(start(config, args.profile, backend))
            elif args.action == "stop":
                sessions = backend.sessions()
                if len(sessions) != 1 or not sessions[0]["name"].startswith(
                    "Workmode/"
                ):
                    raise Error(
                        "No single managed session to stop; use the backend for other sessions"
                    )
                if sessions[0]["locked"]:
                    raise Error("This session is locked until its timer expires")
                backend.stop(sessions[0]["id"])
                print("Session ended")


if __name__ == "__main__":
    try:
        main()
    except (Error, OSError, ValueError, KeyError, TypeError) as exc:
        message = str(exc)
        print(f"Workmode: {message}", file=sys.stderr)
        if os.environ.get("SWIFTBAR") and sys.platform == "darwin":
            # Argument passing avoids interpolating backend error text into AppleScript.
            subprocess.run(
                [
                    "/usr/bin/osascript",
                    "-e",
                    "on run argv",
                    "-e",
                    'display alert "Workmode" message (item 1 of argv)',
                    "-e",
                    "end run",
                    message,
                ],
                check=False,
            )
        sys.exit(1)
