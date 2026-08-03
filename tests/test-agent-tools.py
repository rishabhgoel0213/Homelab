#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(os.environ.get("AGENT_TOOL_SCRIPT", Path(__file__).parent.parent / "scripts" / "agent.py"))


class AgentToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.work = self.root / "work"
        self.codex = self.root / "codex"
        session_id = "019fc434-e6e7-7ef2-9b80-4b876eab8ef1"
        session = self.codex / "sessions" / "2026" / "08" / "02" / f"rollout-{session_id}.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": session_id,
                        "timestamp": "2026-08-02T20:40:29.170Z",
                        "cwd": "/home/rishabh/Agent",
                        "source": "vscode",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (self.codex / "session_index.jsonl").write_text(
            json.dumps(
                {
                    "id": session_id,
                    "thread_name": "Agent workspace redesign",
                    "updated_at": "2026-08-02T21:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "AGENT_STATE_ROOT": str(self.state),
                "AGENT_WORK_ROOT": str(self.work),
                "CODEX_HOME": str(self.codex),
            }
        )

    def tearDown(self):
        self.temporary.cleanup()

    def run_agent(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            check=True,
            capture_output=True,
            text=True,
            env=self.environment,
        )

    def test_indexes_only_session_metadata(self):
        self.run_agent("index", "--quiet")
        record = json.loads((self.state / "index.jsonl").read_text(encoding="utf-8"))
        self.assertEqual("Agent workspace redesign", record["title"])
        self.assertEqual("codex", record["harness"])
        self.assertEqual("/home/rishabh/Agent", record["cwd"])
        self.assertNotIn("messages", record)

    def test_managed_work_lifecycle_is_safe_by_default(self):
        created = Path(self.run_agent("new", "Example task", "--ttl", "1").stdout.strip())
        self.assertTrue(created.is_dir())
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


if __name__ == "__main__":
    unittest.main()
