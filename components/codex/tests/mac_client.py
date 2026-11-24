"""Offline failure handling tests for Mac-side Codex selection and updates."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

COMPONENT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mac_client", COMPONENT / "mac-client.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
PACKAGE = Path("/nix/store/" + "a" * 32 + "-codex-darwin-bundle-0.161.0")
RELEASE = {
    "schema": 1,
    "target": "aarch64-apple-darwin",
    "version": "0.161.0",
    "storePath": str(PACKAGE),
}


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        bootstrap = self.root / "bootstrap"
        bootstrap.mkdir()
        (bootstrap / "codex-package.json").write_text(
            json.dumps({"version": "0.160.0"})
        )
        self.config = {
            "stateDir": str(self.root / "state"),
            "bootstrap": str(bootstrap),
            "ssh": "ssh",
            "sshHost": "rishabh@nixos-pc",
            "releaseFile": "/release.json",
            "nix": "nix",
            "nixEnv": "nix-env",
            "publicKey": "test-public-key",
        }

    def test_manifest_validation(self):
        self.assertEqual(client.validate_release(RELEASE), PACKAGE)
        for change in [
            {"schema": 2},
            {"target": "x86_64-linux"},
            {"version": "0.162.0"},
            {"storePath": "/tmp/untrusted"},
        ]:
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                client.validate_release(RELEASE | change)

    def test_copy_or_signature_failures_never_switch_active_profile(self):
        for fail in ["copy", "verify", "native"]:
            calls = []

            def execute(args, **kwargs):
                calls.append(args)
                if fail in args:
                    raise RuntimeError("test failure")

            with (
                self.subTest(fail=fail),
                patch.object(client, "output", return_value=json.dumps(RELEASE)),
                patch.object(client, "execute", side_effect=execute),
                patch.object(
                    client,
                    "verify_mac",
                    side_effect=RuntimeError("native") if fail == "native" else None,
                ),
            ):
                with self.assertRaises(RuntimeError):
                    client.update(self.config)
                self.assertFalse(
                    any(str(self.root / "state/profile") in call for call in calls)
                )

    def test_verified_update_selects_profile_last(self):
        events = []
        with (
            patch.object(client, "output", return_value=json.dumps(RELEASE)),
            patch.object(
                client, "execute", side_effect=lambda args, **_: events.append(args)
            ),
            patch.object(
                client, "verify_mac", side_effect=lambda *_: events.append(["native"])
            ),
        ):
            client.update(self.config)
        self.assertEqual(events[-2], ["native"])
        self.assertEqual(
            events[-1],
            [
                "nix-env",
                "--profile",
                str(self.root / "state/profile"),
                "--set",
                str(PACKAGE),
            ],
        )

    def test_downgrade_and_unreachable_server_do_not_install(self):
        old = RELEASE | {
            "version": "0.159.0",
            "storePath": str(PACKAGE).replace("0.161.0", "0.159.0"),
        }
        with (
            patch.object(client, "output", return_value=json.dumps(old)),
            patch.object(client, "execute") as execute,
        ):
            with self.assertRaises(RuntimeError):
                client.update(self.config)
            execute.assert_not_called()
        with (
            patch.object(
                client, "output", side_effect=subprocess.TimeoutExpired("ssh", 45)
            ),
            patch.object(client, "execute") as execute,
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                client.update(self.config)
            execute.assert_not_called()

    def test_parser_keeps_codex_config_option(self):
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(self.config))
        expected_cli = str(Path(self.config["bootstrap"]) / "bin/codex")
        with (
            patch(
                "sys.argv",
                [
                    "client",
                    "--config",
                    str(config_path),
                    "run",
                    "--config",
                    "model=test",
                ],
            ),
            patch.object(client.os, "execv") as execv,
        ):
            client.main()
        execv.assert_called_once_with(
            expected_cli, [expected_cli, "--config", "model=test"]
        )


if __name__ == "__main__":
    unittest.main()
