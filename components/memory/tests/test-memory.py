#!/usr/bin/env python3
"""Unit and integration tests for Homelab curated agent memory and t3-history."""

import importlib.util
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMORY_SCRIPT = Path(os.environ.get("MEMORY_SCRIPT", ROOT / "bin" / "memory.py"))
T3_HISTORY_SCRIPT = Path(os.environ.get("T3_HISTORY_SCRIPT", ROOT / "bin" / "t3-history.py"))
WEB_DIR = Path(os.environ.get("MEMORY_WEB_DIR", ROOT / "web"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def create_synthetic_t3_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE projection_projects(
          project_id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          workspace_root TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          deleted_at TEXT,
          archived_at TEXT
        );
        CREATE TABLE orchestration_v2_projection_threads(
          thread_id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL,
          title TEXT NOT NULL,
          default_provider TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          archived_at TEXT,
          deleted_at TEXT,
          payload_json TEXT NOT NULL
        );
        CREATE TABLE orchestration_v2_projection_messages(
          message_id TEXT PRIMARY KEY,
          thread_id TEXT NOT NULL,
          role TEXT NOT NULL,
          streaming INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE orchestration_v2_message_search USING fts5(
          text,
          content = '',
          contentless_delete = 1,
          tokenize = 'trigram remove_diacritics 1'
        );
        """
    )
    conn.execute(
        "INSERT INTO projection_projects VALUES(?, ?, ?, ?, NULL, NULL)",
        ("proj-home", "Homelab", "/home/rishabh/Projects/Homelab", "2026-11-20T10:00:00.000Z"),
    )
    conn.execute(
        "INSERT INTO projection_projects VALUES(?, ?, ?, ?, NULL, NULL)",
        ("proj-school", "Fall 2026", "/home/rishabh/Projects/Fall2026", "2026-11-22T10:00:00.000Z"),
    )

    threads = [
        ("aaaa1111-0000-0000-0000-000000000001", "proj-home", "Tailscale DNS Setup", "antigravity", "2026-11-18T10:00:00.000Z", "2026-11-18T12:00:00.000Z", "2026-11-19T00:00:00.000Z", None, "{}"),
        ("bbbb2222-0000-0000-0000-000000000002", "proj-school", "CMSC216 C Project", "codex", "2026-11-22T14:00:00.000Z", "2026-11-22T16:00:00.000Z", None, None, "{}"),
        ("cccc3333-0000-0000-0000-000000000003", "proj-home", "Subagent Helper", "antigravity", "2026-11-22T15:00:00.000Z", "2026-11-22T15:30:00.000Z", None, None, json.dumps({"lineage": {"relationshipToParent": "subagent"}})),
        ("dddd4444-0000-0000-0000-000000000004", "proj-home", "Deleted Thread", "claude", "2026-11-21T10:00:00.000Z", "2026-11-21T11:00:00.000Z", None, "2026-11-21T12:00:00.000Z", "{}"),
    ]
    conn.executemany(
        "INSERT INTO orchestration_v2_projection_threads VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
        threads,
    )

    messages = [
        ("m1", "aaaa1111-0000-0000-0000-000000000001", "user", 0, "2026-11-18T10:01:00.000Z", "2026-11-18T10:01:00.000Z", json.dumps({"createdBy": "user", "text": "Configure split DNS for internal.therealrishabh.com"})),
        ("m2", "aaaa1111-0000-0000-0000-000000000001", "assistant", 0, "2026-11-18T10:02:00.000Z", "2026-11-18T10:02:00.000Z", json.dumps({"createdBy": "agent", "text": "Updated CoreDNS and Tailscale split DNS records."})),
        ("m3", "bbbb2222-0000-0000-0000-000000000002", "user", 0, "2026-11-22T14:01:00.000Z", "2026-11-22T14:01:00.000Z", json.dumps({"createdBy": "user", "text": "I prefer concise replies without filler. Help debug argv in C."})),
        ("m4", "bbbb2222-0000-0000-0000-000000000002", "assistant", 0, "2026-11-22T14:02:00.000Z", "2026-11-22T14:02:00.000Z", json.dumps({"createdBy": "agent", "text": "Checked argv handling and fixed off-by-one loop."})),
        ("m5", "cccc3333-0000-0000-0000-000000000003", "assistant", 0, "2026-11-22T15:05:00.000Z", "2026-11-22T15:05:00.000Z", json.dumps({"createdBy": "agent", "text": "Subagent internal search output with split DNS."})),
        ("m6", "dddd4444-0000-0000-0000-000000000004", "user", 0, "2026-11-21T10:05:00.000Z", "2026-11-21T10:05:00.000Z", json.dumps({"createdBy": "user", "text": "Deleted secret thread mentioning split DNS."})),
    ]
    for msg in messages:
        cur = conn.execute(
            "INSERT INTO orchestration_v2_projection_messages VALUES(?, ?, ?, ?, ?, ?, ?)",
            msg,
        )
        text = json.loads(msg[6])["text"]
        if msg[1] != "cccc3333-0000-0000-0000-000000000003":
            conn.execute("INSERT INTO orchestration_v2_message_search(rowid, text) VALUES(?, ?)", (cur.lastrowid, text))
    conn.commit()
    conn.close()


class T3HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "statev2.sqlite"
        create_synthetic_t3_db(self.db_path)
        self.mod = load_module("t3_history", T3_HISTORY_SCRIPT)

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_excludes_deleted_and_subagents_and_includes_archived_by_default(self):
        conn = self.mod.open_db(self.db_path)
        try:
            items = self.mod.list_threads(conn)
            ids = [i["thread_id"] for i in items]
            self.assertEqual(ids, ["bbbb2222-0000-0000-0000-000000000002", "aaaa1111-0000-0000-0000-000000000001"])

            active_only = self.mod.list_threads(conn, active_only=True)
            self.assertEqual([i["thread_id"] for i in active_only], ["bbbb2222-0000-0000-0000-000000000002"])

            with_sub = self.mod.list_threads(conn, include_subagents=True)
            self.assertEqual(len(with_sub), 3)
        finally:
            conn.close()

    def test_search_cross_project_archived_and_short_terms(self):
        conn = self.mod.open_db(self.db_path)
        try:
            hits = self.mod.search_threads(conn, "split DNS")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["thread_id"], "aaaa1111-0000-0000-0000-000000000001")
            self.assertTrue(hits[0]["archived"])

            # Short term (< 3 chars) falls back cleanly to LIKE without failing trigram FTS.
            short_hits = self.mod.search_threads(conn, "C")
            self.assertTrue(any(h["thread_id"] == "bbbb2222-0000-0000-0000-000000000002" for h in short_hits))

            # Project filter narrows results.
            filtered = self.mod.search_threads(conn, "split DNS", project="Fall 2026")
            self.assertEqual(filtered, [])
        finally:
            conn.close()

    def test_read_prefix_and_truncation(self):
        conn = self.mod.open_db(self.db_path)
        try:
            data = self.mod.read_thread(conn, "bbbb2222", max_chars=20)
            self.assertEqual(data["thread_id"], "bbbb2222-0000-0000-0000-000000000002")
            self.assertEqual(data["total_messages"], 2)
            self.assertTrue(data["messages"][0]["truncated"])
            self.assertIn("truncated;", data["messages"][0]["text"])
        finally:
            conn.close()

    def test_recent_transcripts_since_watermark(self):
        conn = self.mod.open_db(self.db_path)
        try:
            transcripts = self.mod.recent_transcripts(conn, since="2026-11-20T00:00:00.000Z")
            self.assertEqual([t["thread_id"] for t in transcripts], ["bbbb2222-0000-0000-0000-000000000002"])
        finally:
            conn.close()


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state_dir = self.root / "state"
        self.t3_db = self.root / "statev2.sqlite"
        create_synthetic_t3_db(self.t3_db)

        self.codex_md = self.root / "codex" / "AGENTS.md"
        self.claude_md = self.root / "claude" / "CLAUDE.md"
        self.agy_md = self.root / "antigravity" / "config" / "AGENTS.md"
        for target in (self.codex_md, self.claude_md, self.agy_md):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# Base Policy\n\nKeep this untouched.\n", encoding="utf-8")

        os.environ["MEMORY_STATE"] = str(self.state_dir)
        os.environ["MEMORY_WEB"] = str(WEB_DIR)
        os.environ["MEMORY_URL"] = "https://memory.internal.example.test"
        os.environ["MEMORY_T3_DB"] = str(self.t3_db)
        os.environ["T3_HISTORY_SCRIPT"] = str(T3_HISTORY_SCRIPT)
        os.environ["MEMORY_SYNC_TARGETS"] = ":".join(str(p) for p in (self.codex_md, self.claude_md, self.agy_md))

        self.mod = load_module("memory_mod", MEMORY_SCRIPT)

    def tearDown(self):
        self.tmp.cleanup()

    def test_crud_dedup_secrets_cap_and_sync(self):
        db = self.mod.connect()
        try:
            m1 = self.mod.add_memory(db, category="identity", content="CS student at UMD", source="me", pinned=True)
            self.assertEqual(m1["category"], "identity")
            self.assertTrue(m1["pinned"])

            # Near-duplicate refreshes rather than adding a duplicate row.
            dup = self.mod.add_memory(db, category="identity", content="cs student at umd!", source="agent")
            self.assertTrue(dup.get("deduplicated"))
            self.assertEqual(dup["id"], m1["id"])
            self.assertEqual(len(self.mod.list_memories(db)), 1)

            # Secret guard rejects credentials.
            with self.assertRaises(ValueError):
                self.mod.add_memory(db, category="workflow", content="OpenAI key is sk-proj-1234567890abcdefghijklmnop")

            # Sync injects cleanly and is idempotent.
            res = self.mod.sync_targets(db)
            self.assertEqual(len(res["synced"]), 3)
            for target in (self.codex_md, self.claude_md, self.agy_md):
                text = target.read_text(encoding="utf-8")
                self.assertIn("# Base Policy", text)
                self.assertIn("Keep this untouched.", text)
                self.assertIn("<!-- BEGIN USER MEMORY -->", text)
                self.assertIn("CS student at UMD", text)
                self.assertEqual(text.count("<!-- BEGIN USER MEMORY -->"), 1)

            # Updating re-splices without duplicating markers.
            self.mod.update_memory(db, m1["id"], {"content": "CS major at University of Maryland"}, actor="me")
            self.mod.sync_targets(db)
            text = self.codex_md.read_text(encoding="utf-8")
            self.assertIn("University of Maryland", text)
            self.assertNotIn("CS student at UMD", text)
            self.assertEqual(text.count("<!-- BEGIN USER MEMORY -->"), 1)
        finally:
            db.close()

    def test_capacity_limit_enforced(self):
        db = self.mod.connect()
        old_max = self.mod.MAX_ACTIVE_MEMORIES
        self.mod.MAX_ACTIVE_MEMORIES = 2
        try:
            self.mod.add_memory(db, category="preferences", content="Fact one")
            self.mod.add_memory(db, category="preferences", content="Fact two")
            with self.assertRaises(ValueError):
                self.mod.add_memory(db, category="preferences", content="Fact three")
        finally:
            self.mod.MAX_ACTIVE_MEMORIES = old_max
            db.close()

    def test_consolidation_pin_protection_expiry_and_batch_revert(self):
        db = self.mod.connect()
        try:
            pinned = self.mod.add_memory(db, category="identity", content="Pinned fact", source="me", pinned=True)
            stale = self.mod.add_memory(db, category="ongoing", content="Old trip", source="agent", expires_at="2020-01-01")
            editable = self.mod.add_memory(db, category="preferences", content="Likes concise output", source="agent")

            def fake_llm(prompt, *, backend, model):
                self.assertIn("CMSC216 C Project", prompt)
                return {
                    "summary": "Rishabh is a UMD CS student who prefers concise replies.",
                    "adds": [
                        {
                            "category": "ongoing",
                            "content": "Taking CMSC216 in Fall 2026",
                            "expires_at": "2026-12-22",
                            "reason": "From recent CMSC216 thread",
                        }
                    ],
                    "updates": [
                        {
                            "id": editable["id"],
                            "category": "preferences",
                            "content": "Prefers concise replies without filler",
                            "expires_at": None,
                            "reason": "Clarified in recent chat",
                        }
                    ],
                    "deletes": [
                        {"id": pinned["id"], "reason": "Should be refused because pinned"},
                    ],
                }

            status = self.mod.consolidate(
                db,
                t3_db=self.t3_db,
                since="2026-11-20T00:00:00.000Z",
                runner=fake_llm,
            )
            self.assertTrue(status["ok"])
            self.assertEqual(status["threads_scanned"], 1)
            self.assertEqual(status["expired"], 1)
            self.assertEqual(status["added"], 1)
            self.assertEqual(status["updated"], 1)
            self.assertEqual(status["deleted"], 0)
            self.assertTrue(status["warnings"])  # refused pinned delete

            ids = {m["id"] for m in self.mod.list_memories(db)}
            self.assertIn(pinned["id"], ids)
            self.assertNotIn(stale["id"], ids)
            self.assertIn("concise replies without filler", self.agy_md.read_text(encoding="utf-8"))

            # Second run with no newer threads skips LLM cleanly.
            status2 = self.mod.consolidate(db, t3_db=self.t3_db, runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")))
            self.assertEqual(status2["threads_scanned"], 0)

            # Reverting the entire consolidation batch restores prior state cleanly!
            self.mod.revert_events(db, batch_id=status["batch_id"])
            self.mod.sync_targets(db)
            restored = {m["id"]: m["content"] for m in self.mod.list_memories(db)}
            self.assertEqual(restored[editable["id"]], "Likes concise output")
            self.assertIn(stale["id"], restored)
            self.assertEqual(self.mod.get_meta(db, "summary"), "")
        finally:
            db.close()

    def test_http_api_and_csrf(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.mod.Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=5)

            conn.request("GET", "/healthz")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertTrue(json.loads(resp.read())["ok"])

            conn.request("GET", "/")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertIn(b"Agent Memory", resp.read())

            # Cross-site POST rejected
            conn.request(
                "POST",
                "/api/memories",
                body=json.dumps({"category": "preferences", "content": "Evil"}),
                headers={"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 403)
            resp.read()

            # Valid POST creates and syncs
            conn.request(
                "POST",
                "/api/memories",
                body=json.dumps({"category": "preferences", "content": "Prefer NixOS declarative setups", "pinned": True}),
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 201)
            created = json.loads(resp.read())
            self.assertIn("Prefer NixOS declarative setups", self.claude_md.read_text(encoding="utf-8"))

            # PUT summary
            conn.request(
                "PUT",
                "/api/summary",
                body=json.dumps({"summary": "Runs a declarative NixOS homelab."}),
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            resp.read()

            # DELETE memory
            conn.request(
                "DELETE",
                f"/api/memories/{created['id']}",
                body="{}",
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            resp.read()

            conn.request("GET", "/api/state")
            resp = conn.getresponse()
            state = json.loads(resp.read())
            self.assertEqual(state["count"], 0)
            self.assertEqual(state["summary"], "Runs a declarative NixOS homelab.")
            conn.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
