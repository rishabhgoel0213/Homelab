#!/usr/bin/env python3

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path


SCRIPT = Path(
    os.environ.get(
        "AGENT_SITE_GATEWAY_SCRIPT",
        Path(__file__).parent.parent / "scripts" / "agent-site-gateway.py",
    )
)
SPEC = importlib.util.spec_from_file_location("agent_site_gateway", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
GATEWAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATEWAY)


class AgentSiteGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.work_root = self.root / "work"
        self.work_dir = self.work_root / "2026-08-05-demo-12345678"
        self.work_dir.mkdir(parents=True)
        self.task_id = "12345678-1234-1234-1234-123456789abc"
        (self.work_dir / ".agent-work.json").write_text(
            json.dumps({"schema": 1, "id": self.task_id}), encoding="utf-8"
        )
        self.registry = self.root / "sites.json"
        self.host = "task-demo-12345678.internal.example.test"
        self.entry = {
            "schema": 1,
            "name": "demo",
            "host": self.host,
            "port": 8080,
            "task_id": self.task_id,
            "work_dir": str(self.work_dir),
            "created_at": "2026-08-05T00:00:00Z",
            "expires_at": "2026-08-06T00:00:00Z",
        }
        self.registry.write_text(
            json.dumps({"schema": 1, "sites": [self.entry]}), encoding="utf-8"
        )

    def tearDown(self):
        self.temporary.cleanup()

    def resolve(self, host=None, current_time=None):
        return GATEWAY.resolve_site(
            host or self.host,
            self.registry,
            self.work_root,
            "internal.example.test",
            current_time or datetime(2026, 8, 5, 12, tzinfo=UTC),
        )

    def test_resolves_only_registered_unexpired_managed_site(self):
        self.assertEqual(8080, self.resolve()["port"])
        self.assertIsNone(self.resolve("unregistered.internal.example.test"))
        self.assertIsNone(self.resolve(current_time=datetime(2026, 8, 7, tzinfo=UTC)))

    def test_rejects_manifest_identity_mismatch(self):
        (self.work_dir / ".agent-work.json").write_text(
            json.dumps({"schema": 1, "id": "different"}), encoding="utf-8"
        )
        self.assertIsNone(self.resolve())


if __name__ == "__main__":
    unittest.main()
