"""Unit tests for Zen -> T3 Code browser cookie sync (client and server)."""

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


def load_module(name: str, path_str: str):
    spec = importlib.util.spec_from_file_location(name, path_str)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ZEN_SYNC_PATH = os.environ["T3CODE_ZEN_COOKIE_SYNC"]
RECEIVE_PATH = os.environ["T3CODE_BROWSER_COOKIE_RECEIVE"]
zen_sync = load_module("zen_cookie_sync", ZEN_SYNC_PATH)
cookie_receive = load_module("browser_cookie_receive", RECEIVE_PATH)


def create_zen_cookies_db(profile_dir: Path, rows: list[tuple]) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "cookies.sqlite"
    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute(
            """
            CREATE TABLE moz_cookies (
                id INTEGER PRIMARY KEY,
                originAttributes TEXT NOT NULL DEFAULT '',
                name TEXT,
                value TEXT,
                host TEXT,
                path TEXT,
                expiry INTEGER,
                lastAccessed INTEGER,
                creationTime INTEGER,
                isSecure INTEGER,
                isHttpOnly INTEGER,
                sameSite INTEGER
            )
            """
        )
        con.executemany(
            """
            INSERT INTO moz_cookies (
                originAttributes, name, value, host, path, expiry,
                lastAccessed, creationTime, isSecure, isHttpOnly, sameSite
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        con.commit()
    finally:
        con.close()


class ZenCookieSyncTests(unittest.TestCase):
    def test_profile_discovery_prefers_installs_ini(self):
        with tempfile.TemporaryDirectory() as tmp:
            zen_root = Path(tmp) / "zen"
            p1 = zen_root / "Profiles" / "aaa.default"
            p2 = zen_root / "Profiles" / "bbb.release"
            create_zen_cookies_db(p1, [])
            create_zen_cookies_db(p2, [])
            (zen_root / "installs.ini").write_text(
                "[12345]\nDefault=Profiles/bbb.release\nLocked=1\n",
                encoding="utf-8",
            )
            (zen_root / "profiles.ini").write_text(
                "[Profile0]\nName=default\nIsRelative=1\nPath=Profiles/aaa.default\nDefault=1\n",
                encoding="utf-8",
            )
            self.assertEqual(zen_sync.find_zen_profile(zen_root), p2.resolve())
            self.assertEqual(zen_sync.find_zen_profile(zen_root, "aaa.default"), p1.resolve())

    def test_extract_cookies_filters_and_normalizes_without_touching_passwords(self):
        now = 1_800_000_000
        future = now + 86400 * 30
        expired = now - 60

        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "profile"
            create_zen_cookies_db(
                profile_dir,
                [
                    # Valid Google __Secure- domain cookie
                    ("", "__Secure-1PSID", "secret-token-1", ".google.com", "/", future, 200, 100, 1, 1, 0),
                    # Valid __Host- cookie (leading dot stripped, host-only)
                    ("", "__Host-GAPS", "secret-gaps", ".accounts.google.com", "/", future, 200, 100, 1, 1, 1),
                    # Invalid __Host- cookie (wrong path) -> dropped
                    ("", "__Host-BAD", "bad", "accounts.google.com", "/sub", future, 200, 100, 1, 1, 1),
                    # Non-secure SameSite=None -> downgraded to Lax
                    ("", "prefs", "dark", ".example.com", "/", future, 200, 100, 0, 0, 0),
                    # Session cookie (expiry=0) -> gets 24h TTL
                    ("", "sess", "abc", "app.example.com", "/", 0, 200, 100, 1, 1, 2),
                    # Container duplicate vs default container -> default wins even with lower lastAccessed
                    ("^userContextId=1", "__Secure-1PSID", "container-val", ".google.com", "/", future, 999, 100, 1, 1, 0),
                    # Container-only cookie (e.g. Zen workspace container) -> included
                    ("^userContextId=2", "ws_sid", "ws-val", ".github.com", "/", future, 500, 100, 1, 1, 1),
                    # Private browsing & CHIPS partitioned -> excluded
                    ("^privateBrowsingId=1", "priv", "no", ".google.com", "/", future, 300, 100, 1, 1, 1),
                    ("^partitionKey=(https,example.org)", "part", "no", ".google.com", "/", future, 300, 100, 1, 1, 1),
                    # Expired -> excluded
                    ("", "old", "expired", ".google.com", "/", expired, 100, 100, 1, 1, 1),
                    # Internal / local domains -> excluded
                    ("", "t3", "local", "t3code.internal.therealrishabh.com", "/", future, 200, 100, 1, 1, 1),
                    ("", "ts", "local", "macbook.tail2f4d27.ts.net", "/", future, 200, 100, 1, 1, 1),
                    ("", "dev", "local", "localhost", "/", future, 200, 100, 0, 0, 1),
                    # Custom excluded domain
                    ("", "bank_sid", "nope", ".mybank.com", "/", future, 200, 100, 1, 1, 1),
                ],
            )
            # Create unreadable password files to ensure extractor never touches them.
            for secret_file in ("logins.json", "key4.db"):
                p = profile_dir / secret_file
                p.write_text("DO_NOT_READ", encoding="utf-8")
                os.chmod(p, 0o000)

            try:
                cookies = zen_sync.extract_cookies(
                    profile_dir,
                    exclude_domains=["mybank.com"],
                    now=now,
                )
            finally:
                for secret_file in ("logins.json", "key4.db"):
                    os.chmod(profile_dir / secret_file, 0o600)

            by_key = {(c["domain"], c["name"]): c for c in cookies}
            self.assertEqual(
                set(by_key.keys()),
                {
                    (".google.com", "__Secure-1PSID"),
                    ("accounts.google.com", "__Host-GAPS"),
                    (".example.com", "prefs"),
                    ("app.example.com", "sess"),
                    (".github.com", "ws_sid"),
                },
            )
            self.assertEqual(by_key[(".google.com", "__Secure-1PSID")]["value"], "secret-token-1")
            self.assertEqual(by_key[(".google.com", "__Secure-1PSID")]["sameSite"], "None")
            self.assertEqual(by_key[(".example.com", "prefs")]["sameSite"], "Lax")
            self.assertEqual(by_key[("app.example.com", "sess")]["sameSite"], "Strict")
            self.assertEqual(by_key[("app.example.com", "sess")]["expires"], now + 86400)

            # Domain filter works
            google_only = zen_sync.extract_cookies(
                profile_dir,
                include_domains=["google.com"],
                now=now,
            )
            self.assertEqual(len(google_only), 2)

    def test_cookie_hash_ignores_expiry_bump(self):
        c1 = [
            {
                "name": "SID",
                "value": "v1",
                "domain": ".google.com",
                "path": "/",
                "expires": 1_800_000_100,
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            }
        ]
        c2 = [{**c1[0], "expires": 1_800_099_999}]
        c3 = [{**c1[0], "value": "v2"}]
        self.assertEqual(zen_sync.compute_cookie_hash(c1), zen_sync.compute_cookie_hash(c2))
        self.assertNotEqual(zen_sync.compute_cookie_hash(c1), zen_sync.compute_cookie_hash(c3))

    def test_background_dedup_deferred_retry_and_manual_force(self):
        future = 2_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zen_root = root / "zen"
            profile_dir = zen_root / "Profiles" / "main.default"
            create_zen_cookies_db(
                profile_dir,
                [
                    ("", "SID", "super-secret-value-xyz", ".google.com", "/", future, 100, 100, 1, 1, 1),
                ],
            )
            (zen_root / "installs.ini").write_text(
                "[1]\nDefault=Profiles/main.default\n", encoding="utf-8"
            )

            call_log = root / "ssh-calls.jsonl"
            response_file = root / "ssh-response.json"
            fake_ssh = root / "fake-ssh"
            fake_ssh.write_text(
                f"""#!{sys.executable}
import json, pathlib, sys
stdin_data = sys.stdin.read()
entry = {{"argv": sys.argv[1:], "cookie_count": len(json.loads(stdin_data)["cookies"])}}
with open({str(call_log)!r}, "a", encoding="utf-8") as f:
    f.write(json.dumps(entry) + "\\n")
print(pathlib.Path({str(response_file)!r}).read_text(encoding="utf-8"))
""",
                encoding="utf-8",
            )
            os.chmod(fake_ssh, 0o755)

            state_dir = root / "state"
            cfg_path = root / "config.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "stateDir": str(state_dir),
                        "zenRoot": str(zen_root),
                        "ssh": str(fake_ssh),
                        "sshHost": "rishabh@nixos-pc",
                        "remoteCommand": "t3-browser-cookie-receive",
                        "idleSeconds": 600,
                    }
                ),
                encoding="utf-8",
            )

            # 1. Background run when server returns deferred-busy -> does NOT save last-hash.
            response_file.write_text(
                json.dumps({"status": "deferred-busy", "reason": "recent-activity"}),
                encoding="utf-8",
            )
            r1 = subprocess.run(
                [sys.executable, ZEN_SYNC_PATH, "--config", str(cfg_path), "--background"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertNotIn("super-secret-value-xyz", r1.stdout + r1.stderr)
            self.assertFalse((state_dir / "last-hash").exists())

            # 2. Next background run retries because last-hash wasn't saved, and applies.
            response_file.write_text(
                json.dumps(
                    {
                        "status": "applied",
                        "imported": 1,
                        "skipped": 0,
                        "domains": 1,
                        "restartedBrowser": False,
                    }
                ),
                encoding="utf-8",
            )
            r2 = subprocess.run(
                [sys.executable, ZEN_SYNC_PATH, "--config", str(cfg_path), "--background"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("Synced 1 cookies", r2.stdout)
            self.assertNotIn("super-secret-value-xyz", r2.stdout + r2.stderr)
            self.assertTrue((state_dir / "last-hash").is_file())
            self.assertNotIn(
                "super-secret-value-xyz",
                (state_dir / "last-sync.json").read_text(encoding="utf-8"),
            )

            # 3. Third background run with unchanged cookies skips SSH completely.
            subprocess.run(
                [sys.executable, ZEN_SYNC_PATH, "--config", str(cfg_path), "--background"],
                capture_output=True,
                text=True,
                check=True,
            )
            calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(calls), 2)
            self.assertIn("if-idle", calls[1]["argv"])

            # 4. Manual one-time run always pushes with --mode restart even if hash matches.
            subprocess.run(
                [sys.executable, ZEN_SYNC_PATH, "--config", str(cfg_path)],
                capture_output=True,
                text=True,
                check=True,
            )
            calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(calls), 3)
            self.assertIn("restart", calls[2]["argv"])


class CookieReceiveTests(unittest.TestCase):
    def test_validate_profile_id(self):
        self.assertEqual(cookie_receive.validate_profile_id("default"), "default")
        self.assertEqual(cookie_receive.validate_profile_id("work-1"), "work-1")
        for bad in ("", ".", "..", "incognito", "../etc", "a/b"):
            with self.assertRaises(ValueError):
                cookie_receive.validate_profile_id(bad)

    def test_find_chrome_headless_shell_numeric_version_sort(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            for ver in ("156.0.900.1", "156.0.8078.80"):
                exe = state / "tools" / "chrome-headless-shell" / "linux64" / ver / "chrome-headless-shell"
                exe.parent.mkdir(parents=True, exist_ok=True)
                exe.write_text("#!/bin/sh\n", encoding="utf-8")
                os.chmod(exe, 0o755)
            found = cookie_receive.find_chrome_headless_shell(state)
            self.assertIn("156.0.8078.80", str(found))

    def test_receive_end_to_end_with_fake_injector(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "t3state"
            exe = state / "tools" / "chrome-headless-shell" / "linux64" / "156.0.8078.80" / "chrome-headless-shell"
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_text("#!/bin/sh\n", encoding="utf-8")
            os.chmod(exe, 0o755)

            fake_node = Path(tmp) / "fake-node"
            fake_node.write_text(
                f"""#!{sys.executable}
import json, sys
data = json.loads(sys.stdin.read())
assert len(data["cookies"]) == 1
print(json.dumps({{"imported": 1, "skipped": 0, "skippedDomains": []}}))
""",
                encoding="utf-8",
            )
            os.chmod(fake_node, 0o755)

            payload = json.dumps(
                {
                    "schema": 1,
                    "cookies": [
                        {
                            "name": "SID",
                            "value": "never-log-this-secret",
                            "domain": ".google.com",
                            "path": "/",
                            "expires": 2_000_000_000,
                            "httpOnly": True,
                            "secure": True,
                            "sameSite": "Lax",
                        }
                    ],
                }
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    RECEIVE_PATH,
                    "--state-dir",
                    str(state),
                    "--playwright-path",
                    "/fake/playwright",
                    "--node",
                    str(fake_node),
                    "--injector",
                    "/fake/inject.mjs",
                    "--profile",
                    "default",
                    "--mode",
                    "if-idle",
                ],
                input=payload,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertNotIn("never-log-this-secret", proc.stdout + proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["status"], "applied")
            self.assertEqual(out["imported"], 1)
            self.assertEqual(out["domains"], 1)


if __name__ == "__main__":
    unittest.main()
