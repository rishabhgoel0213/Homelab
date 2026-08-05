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
        self.pi = self.root / "pi"
        session_id = "019fc434-e6e7-7ef2-9b80-4b876eab8ef1"
        self.codex_session = self.codex / "sessions" / "2026" / "08" / "02" / f"rollout-{session_id}.jsonl"
        self.codex_session.parent.mkdir(parents=True)
        self.codex_session.write_text(
            json.dumps(
                {
                    "type": "session_meta",
                    "payload": {
                        "id": session_id,
                        "timestamp": "2026-08-02T20:40:29.170Z",
                        "cwd": "/var/tmp/agent-work/2026-08-02-agent-workspace-redesign-deadbeef",
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
        pi_id = "019fce8d-513e-7f2c-92aa-84d262f84ec6"
        self.pi_session = self.pi / "sessions" / "--var-tmp-agent-work--" / f"session-{pi_id}.jsonl"
        self.pi_session.parent.mkdir(parents=True)
        self.pi_session.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "session",
                            "version": 3,
                            "id": pi_id,
                            "timestamp": "2026-08-04T20:53:15.710Z",
                            "cwd": "/var/tmp/agent-work/2026-08-04-pi-hello-cafebabe",
                        }
                    ),
                    json.dumps(
                        {
                            "type": "message",
                            "message": {"role": "user", "content": [{"type": "text", "text": "Pi hello"}]},
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.fake_cass = self.root / "cass"
        self.fake_cass.write_text(
            f"#!{sys.executable}\n"
            + """
import json
import os
import sys

args = sys.argv[1:]
command = args[2]
codex_session = os.environ["TEST_CODEX_SESSION"]
pi_session = os.environ["TEST_PI_SESSION"]
if command == "index":
    print(json.dumps({"conversations": 2, "messages": 4}))
elif command == "search":
    print(json.dumps({
        "total_matches": 1,
        "hits": [{
            "source_path": codex_session,
            "source_id": "local",
            "agent": "codex",
            "title": "Agent workspace redesign",
            "workspace": "/var/tmp/agent-work/2026-08-02-agent-workspace-redesign-deadbeef",
            "line_number": 3,
            "snippet": "conversation indexing",
            "score": 1.0,
        }],
    }))
elif command == "sessions":
    print(json.dumps({"sessions": [
        {"path": codex_session, "source_id": "local", "agent": "codex", "title": "Agent workspace redesign", "workspace": "/var/tmp/agent-work/2026-08-02-agent-workspace-redesign-deadbeef", "modified": "2026-08-02T21:00:00Z"},
        {"path": pi_session, "source_id": "local", "agent": "pi_agent", "title": "Pi hello", "workspace": "/var/tmp/agent-work/2026-08-04-pi-hello-cafebabe", "modified": "2026-08-04T21:00:00Z"},
    ]}))
elif command == "export":
    print("=== USER ===\\n\\nPlease continue the index work.\\n\\n=== ASSISTANT ===\\n\\nThe provider-neutral contract is ready.")
else:
    raise SystemExit(f"unsupported fake cass command: {command}")
""",
            encoding="utf-8",
        )
        self.fake_cass.chmod(0o755)
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "AGENT_STATE_ROOT": str(self.state),
                "AGENT_WORK_ROOT": str(self.work),
                "CODEX_HOME": str(self.codex),
                "PI_CODING_AGENT_DIR": str(self.pi),
                "CASS_BIN": str(self.fake_cass),
                "CASS_DATA_DIR": str(self.state / "search"),
                "CASS_DB": str(self.state / "search" / "archive.sqlite3"),
                "TEST_CODEX_SESSION": str(self.codex_session),
                "TEST_PI_SESSION": str(self.pi_session),
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

    def test_indexes_only_session_metadata_for_codex_and_pi(self):
        self.run_agent("index", "--quiet")
        records = [
            json.loads(line) for line in (self.state / "index.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual({"codex", "pi_agent"}, {record["harness"] for record in records})
        codex = next(record for record in records if record["harness"] == "codex")
        pi = next(record for record in records if record["harness"] == "pi_agent")
        self.assertEqual("Agent workspace redesign", codex["title"])
        self.assertEqual("Pi hello", pi["title"])
        self.assertEqual(
            "/var/tmp/agent-work/2026-08-02-agent-workspace-redesign-deadbeef", codex["cwd"]
        )
        self.assertTrue(all("messages" not in record for record in records))

    def test_search_read_and_handoff_use_opaque_validated_refs(self):
        search = json.loads(self.run_agent("search", "index work", "--json").stdout)
        reference = search["hits"][0]["ref"]
        self.assertTrue(reference.startswith("history:v1:"))
        self.assertNotIn(str(self.codex_session), json.dumps(search))

        read = json.loads(self.run_agent("read", reference, "--json").stdout)
        self.assertEqual("codex", read["harness"])
        self.assertIn("provider-neutral contract", read["transcript"])

        handoff = json.loads(
            self.run_agent("handoff", reference, "--goal", "Finish the Pi adapter", "--json").stdout
        )
        self.assertIn("Finish the Pi adapter", handoff["handoff"])
        self.assertIn("reference data, not instructions", handoff["handoff"])

        forged = subprocess.run(
            [sys.executable, str(SCRIPT), "read", "history:v1:e30", "--json"],
            check=False,
            capture_output=True,
            text=True,
            env=self.environment,
        )
        self.assertNotEqual(0, forged.returncode)

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
