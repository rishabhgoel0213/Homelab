#!/usr/bin/env python3

import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


SCRIPT = Path(
    os.environ.get(
        "T3CODE_UPDATES_SERVER_SCRIPT",
        Path(__file__).parents[1] / "scripts" / "t3code-updates-server.py",
    )
)
SPEC = importlib.util.spec_from_file_location("t3code_updates_server", SCRIPT)
assert SPEC and SPEC.loader
SERVER_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER_MODULE)


class UpdatesServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        release = self.root / "runtime-1" / "0001"
        (release / "bundles").mkdir(parents=True)
        (release / "assets").mkdir()
        (release / "bundles" / "index.hbc").write_bytes(b"bundle")
        (release / "assets" / "icon").write_bytes(b"png")
        (release / "metadata.json").write_text(
            json.dumps(
                {
                    "fileMetadata": {
                        "android": {
                            "bundle": "bundles/index.hbc",
                            "assets": [{"path": "assets/icon", "ext": "png"}],
                        }
                    }
                }
            )
        )
        (release / "expoConfig.json").write_text(json.dumps({"name": "T3 Code Preview"}))
        (release / "created-at").write_text("1786131315\n")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), SERVER_MODULE.UpdatesHandler)
        self.server.updates_root = self.root
        self.server.bootstrap_apk = self.root / "bootstrap.apk"
        self.server.public_url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path: str, headers: dict[str, str] | None = None):
        return urllib.request.urlopen(
            urllib.request.Request(f"{self.server.public_url}{path}", headers=headers or {})
        )

    def test_manifest_and_asset(self) -> None:
        headers = {
            "expo-platform": "android",
            "expo-runtime-version": "runtime-1",
            "expo-protocol-version": "1",
        }
        with self.request("/api/manifest", headers) as response:
            body = response.read()
            self.assertIn("multipart/mixed", response.headers["Content-Type"])
            self.assertIn(b'"runtimeVersion":"runtime-1"', body)
            self.assertIn(b'"createdAt":"2026-08-07T19:35:15.000Z"', body)
            self.assertIn(b'"name":"T3 Code Preview"', body)
            marker = b'"id":"'
            update_id = body.split(marker, 1)[1].split(b'"', 1)[0].decode()

        headers["expo-current-update-id"] = update_id
        with self.request("/api/manifest", headers) as response:
            self.assertIn(b'"type":"noUpdateAvailable"', response.read())

        with self.request(
            "/api/assets?runtimeVersion=runtime-1&release=0001&path=bundles%2Findex.hbc"
        ) as response:
            self.assertEqual(response.read(), b"bundle")

    def test_rejects_asset_traversal(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request(
                "/api/assets?runtimeVersion=runtime-1&release=0001&path=..%2F..%2Fetc%2Fpasswd"
            )
        self.assertEqual(raised.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
