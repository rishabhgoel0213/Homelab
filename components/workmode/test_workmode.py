import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "workmode", Path(__file__).with_name("workmode.py")
)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)

P = {
    "label": "Study",
    "minutes": 90,
    "locked": True,
    "blocked_apps": ["com.example.Game"],
    "blocked_sites": ["example.com"],
    "launch_apps": [],
    "launch_urls": [],
}


def intention():
    return {
        "id": 4,
        "name": "Workmode/study/test",
        "pausedAt": None,
        "behavior": {
            "type": "block",
            "scope": "blockTargets",
            "enforcementMode": "strict",
            "appTargets": [
                {"action": "block", "app": {"bundleId": "com.example.Game"}}
            ],
            "websiteTargets": [
                {
                    "action": "block",
                    "website": {"hostname": "example.com"},
                    "path": None,
                }
            ],
        },
        "conditions": [
            {"transition": "start", "rule": {"type": "manual"}},
            {
                "transition": "end",
                "rule": {
                    "type": "afterTransition",
                    "anchorTransition": "start",
                    "offsetMs": 5400000,
                },
            },
        ],
    }


class Tests(unittest.TestCase):
    def config(self, p):
        return {"version": 1, "backend": "abstand", "profiles": {"study": p}}

    def test_validate_and_reject_nonportable_settings(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text(json.dumps(self.config(P)))
            self.assertEqual(w.load_config(path), self.config(P))
            for key, value in [
                ("allow_apps", []),
                ("minutes", 0),
                ("locked", "true"),
                ("blocked_sites", ["https://example.com/path"]),
                ("label", "Study | bash=bad"),
                ("launch_apps", ["evil;command"]),
            ]:
                p = dict(P, **{key: value})
                path.write_text(json.dumps(self.config(p)))
                with self.assertRaises(w.Error):
                    w.load_config(path)

    def test_empty_profile_never_touches_backend(self):
        with self.assertRaisesRegex(w.Error, "needs a blocklist"):
            w.start(
                self.config(dict(P, blocked_apps=[], blocked_sites=[])), "study", None
            )

    def test_adapter_rejects_weakened_or_edited_intentions(self):
        item = intention()
        self.assertTrue(w.Abstand.matches(item, P))
        for mutate in [
            lambda x: x["behavior"].update(enforcementMode="casual"),
            lambda x: x["behavior"].update(scope="allowTargets"),
            lambda x: x["behavior"]["websiteTargets"].clear(),
            lambda x: x["conditions"][1]["rule"].update(offsetMs=1),
            lambda x: x.update(pausedAt=1),
        ]:
            edited = copy.deepcopy(item)
            mutate(edited)
            self.assertFalse(w.Abstand.matches(edited, P))

    def test_locked_requires_recovery(self):
        backend = w.Abstand()
        with patch.object(backend, "call", return_value="enabled: false"):
            with self.assertRaises(w.Error):
                backend.check_recovery()

    def test_create_strict_explicit_blockscope_and_targets(self):
        backend = w.Abstand()
        with (
            patch.object(backend, "intentions", return_value=[]),
            patch.object(backend, "call", return_value=intention()) as call,
        ):
            self.assertEqual(backend.prepare("study", P), 4)
            args = call.call_args.args
            self.assertIn("strict", args)
            self.assertIn("--block-site", args)
            self.assertIn("--block-app", args)
            self.assertIn("90m", args)
            self.assertEqual(args[args.index("--scope") + 1], "block")

    def test_lost_start_response_reconciles_without_retry(self):
        backend = w.Abstand()
        with (
            patch.object(backend, "call", side_effect=w.Error("timeout")) as call,
            patch.object(backend, "status", return_value=[{"intentionId": 4}]),
        ):
            backend.start(4)
            self.assertEqual(call.call_count, 1)

    def test_start_failure_never_opens_work_apps(self):
        backend = w.Abstand()
        with (
            patch.object(backend, "ready"),
            patch.object(backend, "sessions", return_value=[]),
            patch.object(backend, "check_recovery"),
            patch.object(backend, "prepare", return_value=4),
            patch.object(backend, "start", side_effect=w.Error("failed")),
            patch.object(w, "run") as launch,
        ):
            with self.assertRaises(w.Error):
                w.start(
                    self.config(dict(P, launch_apps=["com.apple.TextEdit"])),
                    "study",
                    backend,
                )
            launch.assert_not_called()

    def test_active_session_prevents_profile_switch(self):
        backend = w.Abstand()
        with (
            patch.object(backend, "ready"),
            patch.object(backend, "sessions", return_value=[{}]),
            patch.object(backend, "prepare") as prepare,
        ):
            with self.assertRaises(w.Error):
                w.start(self.config(P), "study", backend)
            prepare.assert_not_called()

    def test_menu_unknown_state_does_not_offer_start(self):
        backend = w.Abstand()
        with patch.object(backend, "sessions", side_effect=w.Error("offline")):
            menu = w.menu(self.config(P), backend, "/bin/workmode")
            self.assertIn("Workmode !", menu)
            self.assertNotIn("param1=start", menu)

    def test_menu_locked_has_no_stop_and_waits_for_backend_expiry(self):
        backend = w.Abstand()
        with patch.object(
            backend,
            "sessions",
            return_value=[
                {
                    "id": 4,
                    "name": "Workmode/study/test",
                    "locked": True,
                    "ends_at_ms": 1,
                }
            ],
        ):
            menu = w.menu(self.config(P), backend, "/bin/workmode")
            self.assertIn("finishing", menu)
            self.assertNotIn("param1=stop", menu)
            self.assertNotIn("param1=start", menu)

    def test_old_backend_blocks_switch_when_unverifiable(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "backend").write_text("unavailable")
            with self.assertRaises(w.Error):
                w.guard_backend(Path(d), "abstand")
            self.assertEqual(Path(d, "backend").read_text(), "unavailable")

    def test_status_uses_actual_backend_start_time(self):
        backend = w.Abstand()
        with (
            patch.object(
                backend, "status", return_value=[{"intentionId": 4, "startedAt": 1000}]
            ),
            patch.object(backend, "intentions", return_value=[intention()]),
        ):
            self.assertEqual(backend.sessions()[0]["ends_at_ms"], 5401000)

    def test_pinned_production_version_accepted(self):
        backend = w.Abstand()
        with patch.object(
            backend,
            "call",
            return_value={"version": "v0.1.35p", "pid": 123, "sessions": []},
        ):
            self.assertEqual(backend.status(), [])

    def test_stop_cli_refuses_locked_backend_session(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text(json.dumps(self.config(P)))
            with (
                patch("sys.argv", ["workmode", "--config", str(path), "stop"]),
                patch.dict("os.environ", {"WORKMODE_STATE": d}),
                patch.object(
                    w.Abstand,
                    "sessions",
                    return_value=[
                        {"id": 4, "name": "Workmode/study/test", "locked": True}
                    ],
                ),
                patch.object(w.Abstand, "stop") as stop,
            ):
                with self.assertRaisesRegex(w.Error, "locked"):
                    w.main()
                stop.assert_not_called()

    def test_unexpected_version_rejected(self):
        backend = w.Abstand()
        with patch.object(
            backend, "call", return_value={"version": "0.2", "sessions": []}
        ):
            with self.assertRaises(w.Error):
                backend.status()


if __name__ == "__main__":
    unittest.main()
