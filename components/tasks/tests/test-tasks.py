import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("TASKS_SCRIPT", ROOT / "bin/tasks.py"))
WEB = Path(os.environ.get("TASKS_WEB_DIR", ROOT / "web"))
spec = importlib.util.spec_from_file_location("tasks", SCRIPT)
tasks = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tasks
spec.loader.exec_module(tasks)

TODAY = date(2026, 11, 19)  # a Thursday; its week starts Sunday 2026-11-15


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(tasks, "STATE", Path(self.temp.name) / "state"),
            mock.patch.object(tasks, "WEB", WEB),
            mock.patch.object(tasks, "today", lambda: TODAY),
        ]
        for patch in self.patches:
            patch.start()
        self.db = tasks.connect()

    def tearDown(self):
        self.db.close()
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()


class WeekTests(Base):
    def test_weeks_start_on_sunday(self):
        self.assertEqual(tasks.week_start(date(2026, 11, 15)), date(2026, 11, 15))
        self.assertEqual(tasks.week_start(date(2026, 11, 21)), date(2026, 11, 15))
        self.assertEqual(tasks.week_start(date(2026, 11, 22)), date(2026, 11, 22))

    def test_resolve_week_keywords(self):
        self.assertEqual(tasks.resolve_week(None), date(2026, 11, 15))
        self.assertEqual(tasks.resolve_week("next"), date(2026, 11, 22))
        self.assertEqual(tasks.resolve_week("last"), date(2026, 11, 8))
        self.assertEqual(tasks.resolve_week("+2"), date(2026, 11, 29))
        self.assertEqual(tasks.resolve_week("2026-12-02"), date(2026, 11, 29))
        with self.assertRaises(ValueError):
            tasks.resolve_week("someday")

    def test_resolve_day(self):
        week = date(2026, 11, 15)
        self.assertEqual(tasks.resolve_day("fri", week), (week, 5))
        self.assertEqual(tasks.resolve_day("Sunday", week), (week, 0))
        self.assertEqual(tasks.resolve_day(None, week), (week, None))
        self.assertEqual(tasks.resolve_day("anytime", week), (week, None))
        self.assertEqual(tasks.resolve_day("today", date(2026, 1, 4)), (week, 4))
        self.assertEqual(tasks.resolve_day("2026-11-22", week), (date(2026, 11, 22), 0))
        self.assertEqual(tasks.resolve_day(6, week), (week, 6))
        for bad in (7, True, "funday", 1.5):
            with self.assertRaises(ValueError):
                tasks.resolve_day(bad, week)

    def test_quick_parse(self):
        self.assertEqual(tasks.parse_quick("fri: call dentist"), ("fri", "call dentist"))
        self.assertEqual(tasks.parse_quick("Today: groceries"), ("today", "groceries"))
        self.assertEqual(tasks.parse_quick("Note: buy milk"), (None, "Note: buy milk"))
        self.assertEqual(tasks.parse_quick("plain task"), (None, "plain task"))


class StoreTests(Base):
    def test_add_list_and_order(self):
        created = tasks.add_tasks(self.db, [
            {"title": "Plan week"},
            {"title": "Gym", "day": "mon"},
            {"text": "fri: call dentist", "notes": "ask about Dec"},
            "tomorrow: groceries",
        ], "agent")
        self.assertEqual([t["day"] for t in created], [None, "mon", "fri", "fri"])
        self.assertEqual(created[2]["date"], "2026-11-20")
        board = tasks.list_week(self.db)
        self.assertEqual(board["week"], "2026-11-15")
        self.assertEqual(board["week_end"], "2026-11-21")
        self.assertEqual(board["days"][0], {"day": "sun", "name": "Sunday", "date": "2026-11-15"})
        self.assertEqual([t["title"] for t in board["tasks"]], ["Plan week", "Gym", "call dentist", "groceries"])
        self.assertEqual(board["summary"], {"total": 4, "done": 0, "open": 4})
        self.assertTrue(all(t["source"] == "agent" for t in board["tasks"]))

    def test_validation_is_atomic(self):
        with self.assertRaises(ValueError):
            tasks.add_tasks(self.db, [{"title": "ok"}, {"title": "  "}], "me")
        with self.assertRaises(ValueError):
            tasks.add_tasks(self.db, [{"title": "x", "colour": "red"}], "me")
        self.assertEqual(tasks.list_week(self.db)["tasks"], [])

    def test_update_done_move_and_delete(self):
        task = tasks.add_tasks(self.db, [{"title": "Write report", "day": "tue"}], "me")[0]
        rev = tasks.revision(self.db)
        done = tasks.update_task(self.db, task["id"], {"done": True})
        self.assertTrue(done["done"])
        self.assertIsNotNone(done["completed_at"])
        self.assertGreater(tasks.revision(self.db), rev)
        moved = tasks.update_task(self.db, task["id"], {"week": "next", "day": "wed", "done": False})
        self.assertEqual((moved["week"], moved["day"], moved["done"]), ("2026-11-22", "wed", False))
        self.assertIsNone(moved["completed_at"])
        same_week = tasks.update_task(self.db, task["id"], {"day": "anytime"})
        self.assertEqual((same_week["week"], same_week["day"]), ("2026-11-22", None))
        tasks.delete_task(self.db, task["id"])
        with self.assertRaises(tasks.NotFound):
            tasks.update_task(self.db, task["id"], {"done": True})

    def test_reorder_moves_between_lanes(self):
        a, b, c = tasks.add_tasks(self.db, [{"title": "a", "day": "mon"}, {"title": "b", "day": "mon"},
                                            {"title": "c"}], "me")
        board = tasks.reorder(self.db, "2026-11-15", "mon", [c["id"], b["id"], a["id"]])
        monday = [t["title"] for t in board["tasks"] if t["day"] == "mon"]
        self.assertEqual(monday, ["c", "b", "a"])

    def test_carry_over_unfinished(self):
        old = tasks.add_tasks(self.db, [{"title": "unfinished", "day": "thu"}, {"title": "finished"}],
                              "me", week="last")
        tasks.update_task(self.db, old[1]["id"], {"done": True})
        self.assertEqual(tasks.list_week(self.db)["previous_unfinished"], 1)
        result = tasks.carry_over(self.db)
        self.assertEqual((result["from_week"], result["to_week"], result["moved"]), ("2026-11-08", "2026-11-15", 1))
        board = tasks.list_week(self.db)
        self.assertEqual([(t["title"], t["day"]) for t in board["tasks"]], [("unfinished", None)])
        self.assertEqual(board["previous_unfinished"], 0)
        self.assertEqual(len(tasks.list_week(self.db, "last")["tasks"]), 1)


class McpTests(Base):
    def run_mcp(self, *messages):
        stdin = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout):
            tasks.mcp()
        return [json.loads(line) for line in stdout.getvalue().splitlines()]

    def test_initialize_list_and_call(self):
        responses = self.run_mcp(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "add_tasks", "arguments": {
                "tasks": [{"title": "Laundry", "day": "sat"}, {"title": "Read paper", "notes": "arXiv"}]}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "list_tasks", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "update_task", "arguments": {
                "task_id": "nope", "done": True}}},
        )
        self.assertEqual([r["id"] for r in responses], [1, 2, 3, 4, 5])
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "tasks")
        names = {t["name"] for t in responses[1]["result"]["tools"]}
        self.assertEqual(names, {"list_tasks", "add_tasks", "update_task", "delete_task", "carry_over"})
        created = responses[2]["result"]["structuredContent"]["created"]
        self.assertEqual([t["source"] for t in created], ["agent", "agent"])
        listed = responses[3]["result"]["structuredContent"]
        self.assertEqual(listed["summary"]["total"], 2)
        self.assertTrue(responses[4]["result"]["isError"])


class HttpTests(Base):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), tasks.Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def request(self, method, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        merged = {"Content-Type": "application/json"} if body is not None else {}
        merged.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=merged)
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, res.read(), res.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def test_page_and_api_round_trip(self):
        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>Weekly Tasks</title>", body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        status, body, _ = self.request("POST", "/api/tasks", {"text": "wed: dentist", "week": "2026-11-15"})
        self.assertEqual(status, 201)
        task = json.loads(body)
        self.assertEqual((task["day"], task["source"]), ("wed", "me"))
        status, body, _ = self.request("PATCH", f"/api/tasks/{task['id']}", {"done": True})
        self.assertTrue(json.loads(body)["done"])
        status, body, _ = self.request("GET", "/api/week?week=2026-11-18")
        self.assertEqual(json.loads(body)["summary"], {"total": 1, "done": 1, "open": 0})
        self.assertEqual(self.request("PATCH", "/api/tasks/missing", {"done": True})[0], 404)
        self.assertEqual(self.request("POST", "/api/tasks", {"title": ""})[0], 400)
        self.assertEqual(self.request("DELETE", f"/api/tasks/{task['id']}", {})[0], 200)

    def test_cross_site_writes_are_refused(self):
        form = urllib.request.Request(self.base + "/api/tasks", data=b"title=x", method="POST",
                                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(form)
        self.assertEqual(caught.exception.code, 403)
        status, _, _ = self.request("POST", "/api/tasks", {"title": "x"}, {"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", "/api/tasks", {"title": "x"}, {"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)
        self.assertEqual(tasks.list_week(self.db)["tasks"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
