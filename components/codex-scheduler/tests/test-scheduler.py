import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock


SCRIPT = Path(os.environ.get("CODEX_SCHEDULER_SCRIPT", Path(__file__).parent.parent / "bin/codex-scheduler.py"))
spec = importlib.util.spec_from_file_location("scheduler", SCRIPT)
scheduler = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scheduler
spec.loader.exec_module(scheduler)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "projects" / "coursework"
        self.project.mkdir(parents=True)
        self.patches = [
            mock.patch.object(scheduler, "STATE", self.root / "state"),
            mock.patch.object(scheduler, "ROOTS", [str(self.root / "projects")]),
        ]
        for patch in self.patches:
            patch.start()
        self.db = scheduler.connect()

    def tearDown(self):
        self.db.close()
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def create(self, **updates):
        args = {"name": "Homework", "project": str(self.project), "prompt": "Check Canvas and prepare new homework.",
                "schedule": {"frequency": "weekly", "weekdays": [1], "time": "09:00", "timezone": "America/New_York"}, **updates}
        return scheduler.dispatch(self.db, "create_job", args)

    def test_weekly_dst_and_nonexistent_time(self):
        schedule = scheduler.validate_schedule({"frequency": "weekly", "weekdays": [1], "time": "09:00", "timezone": "America/New_York"})
        self.assertEqual(datetime(2026, 11, 2, 14, tzinfo=UTC), scheduler.next_time(schedule, datetime(2026, 10, 27, tzinfo=UTC)))
        daily = {"frequency": "daily", "time": "02:30", "timezone": "America/New_York"}
        self.assertEqual(datetime(2026, 3, 9, 6, 30, tzinfo=UTC), scheduler.next_time(daily, datetime(2026, 3, 8, 6, tzinfo=UTC)))
        fall = {"frequency": "daily", "time": "01:30", "timezone": "America/New_York"}
        self.assertEqual(datetime(2026, 11, 2, 6, 30, tzinfo=UTC), scheduler.next_time(fall, datetime(2026, 11, 1, 5, 45, tzinfo=UTC)))

    def test_creation_persistence_and_duplicate_name(self):
        job = self.create()
        other = scheduler.connect()
        try:
            self.assertEqual(job, scheduler.get_job(other, job["id"]))
        finally:
            other.close()
        with self.assertRaises(sqlite3.IntegrityError):
            self.create()
        self.assertEqual(1, len(scheduler.dispatch(self.db, "list_jobs", {})["jobs"]))
        self.assertEqual(0o600, (scheduler.STATE / "scheduler.db").stat().st_mode & 0o777)

    def test_invalid_inputs_and_symlink_escape(self):
        outside = self.root / "outside"
        outside.mkdir()
        escape = self.project / "escape"
        escape.symlink_to(outside, target_is_directory=True)
        for value in [str(outside), str(escape), str(self.project.parent), "relative"]:
            with self.assertRaises(ValueError):
                self.create(project=value)
        for updates in [{"timeout_seconds": 0}, {"enabled": "true"}, {"model": "x\n--bad"}, {"prompt": ""}, {"extra": True}]:
            with self.assertRaises(ValueError):
                self.create(**updates)
        for schedule in [{"frequency": "once", "run_at": "2026-12-01T10:00:00"},
                         {"frequency": "weekly", "weekdays": [True], "time": "09:00", "timezone": "UTC"},
                         {"frequency": "daily", "time": "25:00", "timezone": "UTC"}]:
            with self.assertRaises(ValueError):
                self.create(schedule=schedule)

    def test_pause_resume_and_queue_idempotence(self):
        job = self.create()
        queued = scheduler.dispatch(self.db, "run_now", {"job_id": job["id"]})
        self.assertEqual(queued, scheduler.dispatch(self.db, "run_now", {"job_id": job["id"]}))
        paused = scheduler.dispatch(self.db, "pause_job", {"job_id": job["id"]})
        self.assertFalse(paused["enabled"])
        self.assertEqual("cancelled", scheduler.dispatch(self.db, "get_runs", {})["runs"][0]["status"])
        resumed = scheduler.dispatch(self.db, "update_job", {"job_id": job["id"], "enabled": True})
        self.assertIsNotNone(resumed["next_run_at"])

    def test_end_date_and_one_off(self):
        now = scheduler.utc_now()
        at = now + timedelta(minutes=1)
        job = self.create(schedule={"frequency": "once", "run_at": scheduler.stamp(at)})
        scheduler.enqueue_due(self.db, at + timedelta(seconds=1))
        self.assertFalse(scheduler.get_job(self.db, job["id"])["enabled"])
        self.assertEqual(1, len(scheduler.dispatch(self.db, "get_runs", {})["runs"]))
        scheduler.enqueue_due(self.db, at + timedelta(minutes=10))
        self.assertEqual(1, len(scheduler.dispatch(self.db, "get_runs", {})["runs"]))
        with self.assertRaises(ValueError):
            self.create(name="expired", end_at=scheduler.stamp(now - timedelta(seconds=1)))

    def test_missed_runs_coalesce_and_expiry(self):
        job = self.create(schedule={"frequency": "daily", "time": "09:00", "timezone": "UTC"})
        past = scheduler.utc_now() - timedelta(days=20)
        self.db.execute("UPDATE jobs SET next_run_at=? WHERE id=?", (scheduler.stamp(past), job["id"]))
        scheduler.enqueue_due(self.db, scheduler.utc_now())
        scheduler.enqueue_due(self.db, scheduler.utc_now())
        self.assertEqual(1, len(scheduler.dispatch(self.db, "get_runs", {})["runs"]))
        self.assertGreater(scheduler.parse_date(scheduler.get_job(self.db, job["id"])["next_run_at"]), scheduler.utc_now())
        expired = self.create(name="ending", end_at=scheduler.stamp(scheduler.utc_now() + timedelta(days=10)))
        scheduler.enqueue_due(self.db, scheduler.utc_now() + timedelta(days=11))
        self.assertFalse(scheduler.get_job(self.db, expired["id"])["enabled"])
        self.assertEqual([], scheduler.dispatch(self.db, "get_runs", {"job_id": expired["id"]})["runs"])

    def test_changed_job_cancels_queued_snapshot(self):
        job = self.create()
        scheduler.dispatch(self.db, "run_now", {"job_id": job["id"]})
        scheduler.dispatch(self.db, "update_job", {"job_id": job["id"], "prompt": "New prompt"})
        self.assertEqual("cancelled", scheduler.dispatch(self.db, "get_runs", {})["runs"][0]["status"])

    def test_tick_success_with_real_child_process(self):
        fake = self.root / "fake-codex.py"
        fake.write_text('import json,sys\nfrom pathlib import Path\nargs=sys.argv\nPath(args[args.index("--output-last-message")+1]).write_text("Prepared homework")\nprint(json.dumps({"type":"thread.started","thread_id":"test-thread"}))\nassert sys.stdin.read()=="Check Canvas and prepare new homework."\n')
        job = self.create(enabled=False)
        scheduler.dispatch(self.db, "run_now", {"job_id": job["id"]})
        original = scheduler.codex_command
        def command(data, summary):
            return [sys.executable, str(fake), *original(data, summary)[1:]]
        with mock.patch.object(scheduler, "codex_command", side_effect=command):
            scheduler.tick()
        run = scheduler.dispatch(self.db, "get_runs", {})["runs"][0]
        self.assertEqual("succeeded", run["status"])
        self.assertEqual("Prepared homework", run["summary"])
        self.assertEqual("test-thread", run["thread_id"])
        argv = original(job, self.root / "summary")
        self.assertIn("workspace-write", argv)
        self.assertIn("--approve-for-me", argv)
        self.assertIn('approval_policy="on-request"', argv)
        self.assertIn('approvals_reviewer="auto_review"', argv)
        self.assertIn("mcp_servers.codex-scheduler.enabled=false", argv)
        self.assertEqual("-", argv[-1])

    def test_tick_failure_and_interruption_recovery(self):
        job = self.create(enabled=False)
        first = scheduler.dispatch(self.db, "run_now", {"job_id": job["id"]})
        self.db.execute("UPDATE runs SET status='running' WHERE id=?", (first["id"],))
        with mock.patch.object(scheduler, "CODEX", str(self.root / "missing")):
            scheduler.tick()
            scheduler.dispatch(self.db, "run_now", {"job_id": job["id"]})
            scheduler.tick()
        runs = scheduler.dispatch(self.db, "get_runs", {})["runs"]
        self.assertEqual(["failed", "interrupted"], [run["status"] for run in runs])

    def test_timeout_kills_process_group(self):
        job = self.create(enabled=False)
        queued = scheduler.dispatch(self.db, "run_now", {"job_id": job["id"]})
        process = mock.Mock(pid=1234, returncode=-9)
        process.communicate.side_effect = [scheduler.subprocess.TimeoutExpired("codex", 30), (None, None)]
        with mock.patch.object(scheduler.subprocess, "Popen", return_value=process), mock.patch.object(scheduler.os, "killpg") as kill:
            scheduler.execute_run(self.db, queued, job)
        kill.assert_called_once_with(1234, scheduler.signal.SIGKILL)
        self.assertEqual("timed_out", scheduler.dispatch(self.db, "get_runs", {})["runs"][0]["status"])

    def test_global_dispatcher_lock(self):
        job = self.create(enabled=False)
        scheduler.dispatch(self.db, "run_now", {"job_id": job["id"]})
        with (scheduler.STATE / "dispatcher.lock").open("a") as lock:
            scheduler.fcntl.flock(lock, scheduler.fcntl.LOCK_EX | scheduler.fcntl.LOCK_NB)
            with mock.patch.object(scheduler, "execute_run") as execute:
                scheduler.tick()
                execute.assert_not_called()
        self.assertEqual("queued", scheduler.dispatch(self.db, "get_runs", {})["runs"][0]["status"])

    def test_delete_requires_paused_and_no_active_run(self):
        job = self.create()
        with self.assertRaises(ValueError):
            scheduler.dispatch(self.db, "delete_job", {"job_id": job["id"]})
        scheduler.dispatch(self.db, "pause_job", {"job_id": job["id"]})
        scheduler.dispatch(self.db, "delete_job", {"job_id": job["id"]})
        self.assertEqual([], scheduler.dispatch(self.db, "list_jobs", {})["jobs"])

    def test_stdio_mcp_and_errors(self):
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_jobs", "arguments": {}}},
                    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_job", "arguments": {"job_id": "missing"}}}]
        output = io.StringIO()
        with mock.patch.object(scheduler.sys, "stdin", io.StringIO("\n".join(map(json.dumps, requests)))), mock.patch.object(scheduler.sys, "stdout", output):
            scheduler.mcp()
        responses = list(map(json.loads, output.getvalue().splitlines()))
        self.assertEqual(4, len(responses))
        self.assertEqual("2025-11-25", responses[0]["result"]["protocolVersion"])
        self.assertEqual(8, len(responses[1]["result"]["tools"]))
        self.assertEqual({"jobs": []}, responses[2]["result"]["structuredContent"])
        self.assertTrue(responses[3]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
