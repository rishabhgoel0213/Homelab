import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WRAPPER = Path(
    os.environ.get(
        "GOG_WRAPPER_SCRIPT",
        Path(__file__).resolve().parent / "bin" / "gog-wrapper",
    )
)


class GogWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.fake_gog = self.root / "fake-gog"
        self.fake_gog.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "print(json.dumps({\n"
            "    'argv': sys.argv[1:],\n"
            "    'XDG_CONFIG_HOME': os.environ.get('XDG_CONFIG_HOME'),\n"
            "    'GOG_KEYRING_BACKEND': os.environ.get('GOG_KEYRING_BACKEND'),\n"
            "    'GOG_KEYRING_PASSWORD': os.environ.get('GOG_KEYRING_PASSWORD'),\n"
            "    'GOG_ACCOUNT': os.environ.get('GOG_ACCOUNT'),\n"
            "}))\n"
        )
        self.fake_gog.chmod(0o755)

    def tearDown(self):
        self.temp.cleanup()

    def run_wrapper(self, args, extra_env=None):
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "GOG_STATE_DIR": str(self.state),
            "GOG_REAL_BIN": str(self.fake_gog),
        }
        if extra_env:
            env.update(extra_env)
        proc = subprocess.run(
            ["bash", str(WRAPPER), *args],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(proc.stdout)

    def test_generates_persistent_keyring_key_and_sets_defaults(self):
        first = self.run_wrapper(["auth", "status"])
        self.assertEqual(first["argv"], ["auth", "status"])
        self.assertEqual(first["XDG_CONFIG_HOME"], str(self.state / "config"))
        self.assertEqual(first["GOG_KEYRING_BACKEND"], "file")
        self.assertIsNone(first["GOG_ACCOUNT"])
        self.assertEqual(len(first["GOG_KEYRING_PASSWORD"]), 64)

        key_file = self.state / "keyring.key"
        self.assertTrue(key_file.exists())
        self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)

        second = self.run_wrapper(["drive", "ls"])
        self.assertEqual(second["GOG_KEYRING_PASSWORD"], first["GOG_KEYRING_PASSWORD"])

    def test_loads_default_account_and_respects_overrides(self):
        self.state.mkdir(parents=True, mode=0o700)
        (self.state / "default-account").write_text("# comment\n  user@example.com  \n")

        res = self.run_wrapper(["gmail", "search", "is:unread"])
        self.assertEqual(res["GOG_ACCOUNT"], "user@example.com")

        override = self.run_wrapper(
            ["gmail", "search", "is:unread"],
            extra_env={
                "GOG_ACCOUNT": "other@example.com",
                "GOG_KEYRING_PASSWORD": "explicit-password",
            },
        )
        self.assertEqual(override["GOG_ACCOUNT"], "other@example.com")
        self.assertEqual(override["GOG_KEYRING_PASSWORD"], "explicit-password")


if __name__ == "__main__":
    unittest.main()
