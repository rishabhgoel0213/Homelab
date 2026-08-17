#!/usr/bin/env python3

import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


SCRIPT = Path(os.environ.get("AGENT_TOOL_SCRIPT", Path(__file__).parent.parent / "scripts" / "agent.py"))


class AgentToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.work = self.root / "work"
        self.policy = self.root / "policy"
        self.policy.mkdir()
        for name in ("AGENTS.md", "ENVIRONMENT.md", "MEMORY.md", "README.md"):
            (self.policy / name).write_text(f"canonical {name}\n", encoding="utf-8")
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "AGENT_STATE_ROOT": str(self.state),
                "AGENT_WORK_ROOT": str(self.work),
                "AGENT_POLICY_ROOT": str(self.policy),
                "AGENT_SITE_REGISTRY": str(self.state / "sites.json"),
                "AGENT_SITE_DOMAIN": "internal.example.test",
            }
        )

    def tearDown(self):
        self.temporary.cleanup()

    def run_agent(self, *arguments, cwd=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            check=True,
            capture_output=True,
            text=True,
            env=self.environment,
            cwd=cwd,
        )

    def test_managed_work_lifecycle_is_safe_by_default(self):
        created = Path(self.run_agent("new", "Example task", "--ttl", "1").stdout.strip())
        self.assertTrue(created.is_dir())
        for name in ("AGENTS.md", "ENVIRONMENT.md", "MEMORY.md", "README.md"):
            self.assertEqual(f"canonical {name}\n", (created / name).read_text(encoding="utf-8"))
        (created / "MEMORY.md").unlink()
        self.run_agent("policy-sync", "--quiet")
        self.assertEqual(
            "canonical MEMORY.md\n", (created / "MEMORY.md").read_text(encoding="utf-8")
        )
        self.run_agent("keep", str(created))
        manifest_path = created / ".agent-work.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual("keep", manifest["retention"])

        self.run_agent("release", str(created), "--days", "1")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["expires_at"] = "2000-01-01T00:00:00Z"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        dry_run = self.run_agent("gc")
        self.assertIn("would-delete", dry_run.stdout)
        self.assertTrue(created.exists())
        self.run_agent("gc", "--apply", "--quiet")
        self.assertFalse(created.exists())

    def test_gc_ignores_unmanaged_directories(self):
        unmanaged = self.work / "unmanaged"
        unmanaged.mkdir(parents=True)
        self.run_agent("gc", "--apply", "--quiet")
        self.assertTrue(unmanaged.exists())

    def test_temporary_site_lifecycle_is_scoped_to_managed_task(self):
        created = Path(self.run_agent("new", "Site task", "--ttl", "1").stdout.strip())
        nested = created / "app"
        nested.mkdir()

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.recv(1024)

        with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            exposed = self.run_agent(
                "site", "expose", str(port), "--name", "demo", "--ttl", "30m", cwd=nested
            )
            url = exposed.stdout.strip()
            self.assertRegex(url, r"^https://task-demo-[0-9a-f]{8}\.internal\.example\.test$")

            registry = json.loads((self.state / "sites.json").read_text(encoding="utf-8"))
            self.assertEqual(port, registry["sites"][0]["port"])
            self.assertEqual(str(created), registry["sites"][0]["work_dir"])
            self.assertIn(url.removeprefix("https://"), self.run_agent("site", "list").stdout)

            self.run_agent("site", "stop", "demo", cwd=nested)
            registry = json.loads((self.state / "sites.json").read_text(encoding="utf-8"))
            self.assertEqual([], registry["sites"])

    def test_temporary_site_rejects_unmanaged_cwd_and_unreachable_port(self):
        outside = subprocess.run(
            [sys.executable, str(SCRIPT), "site", "expose", "9"],
            check=False,
            capture_output=True,
            text=True,
            env=self.environment,
            cwd=self.root,
        )
        self.assertNotEqual(0, outside.returncode)

        created = Path(self.run_agent("new", "No server", "--ttl", "1").stdout.strip())
        unreachable = subprocess.run(
            [sys.executable, str(SCRIPT), "site", "expose", "9", "--ttl", "4h"],
            check=False,
            capture_output=True,
            text=True,
            env=self.environment,
            cwd=created,
        )
        self.assertNotEqual(0, unreachable.returncode)
        self.assertIn("nothing is accepting connections", unreachable.stderr)


if __name__ == "__main__":
    unittest.main()
