"""Validate Mac T3 Code signed-release checks, nightly ordering, and serve arguments."""
import importlib.util
import os
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


def load_client():
    client_path = Path(os.environ.get("T3CODE_MAC_CLIENT", str(ROOT / "mac-client.py")))
    spec = importlib.util.spec_from_file_location("t3code_mac_client", client_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MacClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client()

    def test_validate_release_rejects_untrusted_payloads(self):
        prefix = "/nix/store/" + "a" * 32 + "-t3code-darwin-"
        bad_payloads = [
            {},
            {"schema": 1, "target": "darwin-arm64", "storePath": "/tmp/t3", "version": "0.1.8-nightly.20261105.4218"},
            {"schema": 2, "target": "darwin-arm64", "storePath": prefix + "0.1.8-nightly.20261105.4218", "version": "0.1.8-nightly.20261105.4218"},
            {"schema": 1, "target": "linux-x64", "storePath": prefix + "0.1.8-nightly.20261105.4218", "version": "0.1.8-nightly.20261105.4218"},
            {"schema": 1, "target": "darwin-arm64", "storePath": prefix + "0.1.8-nightly.20261105.4218", "version": "0.1.8-nightly.20261106.4220"},
        ]
        for payload in bad_payloads:
            with self.assertRaises(RuntimeError):
                self.client.validate_release(payload)

    def test_validate_release_accepts_valid_nightly(self):
        version = "0.1.8-nightly.20261105.4218"
        store_path = "/nix/store/" + "a" * 32 + f"-t3code-darwin-{version}"
        resolved = self.client.validate_release(
            {"schema": 1, "target": "darwin-arm64", "storePath": store_path, "version": version}
        )
        self.assertEqual(str(resolved), store_path)

    def test_version_key_orders_nightlies(self):
        vk = self.client.version_key
        self.assertLess(vk("0.1.8-nightly.20261105.4218"), vk("0.1.8-nightly.20261105.4219"))
        self.assertLess(vk("0.1.8-nightly.20261105.9999"), vk("0.1.8-nightly.20261106.1"))
        self.assertLess(vk("0.1.8-nightly.20261105.4218"), vk("0.1.9-nightly.20260101.1"))
        with self.assertRaises(RuntimeError):
            vk("0.1.8")

    def test_serve_args_with_and_without_tailscale(self):
        base = {
            "port": 3773,
            "dataDir": "/Users/rishabhgoel/.local/state/t3code",
            "tailscaleServe": True,
            "tailscaleServePort": 443,
        }
        self.assertEqual(
            self.client.serve_args(base, "/nix/store/x/t3", []),
            [
                "/nix/store/x/t3",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                "3773",
                "--base-dir",
                "/Users/rishabhgoel/.local/state/t3code",
                "--no-browser",
                "--tailscale-serve",
                "--tailscale-serve-port",
                "443",
            ],
        )
        no_ts = {**base, "tailscaleServe": False}
        self.assertEqual(
            self.client.serve_args(no_ts, "/nix/store/x/t3", ["--log-ws-events"]),
            [
                "/nix/store/x/t3",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                "3773",
                "--base-dir",
                "/Users/rishabhgoel/.local/state/t3code",
                "--no-browser",
                "--log-ws-events",
            ],
        )


if __name__ == "__main__":
    unittest.main()
