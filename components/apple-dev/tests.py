import hashlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(
    os.environ.get(
        "APPLE_DEV_SCRIPT",
        Path(__file__).resolve().parent / "apple-dev.py",
    )
)


def load_module():
    spec = importlib.util.spec_from_file_location("apple_dev_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AppleDevTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_select_ios_runtime_prefers_matched_build(self):
        runtimes = {
            "A": {
                "identifier": "A",
                "build": "24B91016s",
                "version": "27.2",
                "state": "Ready",
                "platformIdentifier": "com.apple.platform.iphonesimulator",
                "runtimeIdentifier": "com.apple.CoreSimulator.SimRuntime.iOS-27-2-iPhone19-4",
            },
            "B": {
                "identifier": "B",
                "build": "24B8117",
                "version": "27.2",
                "state": "Ready",
                "platformIdentifier": "com.apple.platform.iphonesimulator",
                "runtimeIdentifier": "com.apple.CoreSimulator.SimRuntime.iOS-27-2",
            },
        }
        match = {
            "iphoneos27.2": {
                "platform": "com.apple.platform.iphoneos",
                "chosenRuntimeBuild": "24B8117",
            }
        }
        chosen = self.mod.select_ios_runtime(runtimes, match)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["build"], "24B8117")

        override = self.mod.select_ios_runtime(runtimes, match, runtime_id="A")
        self.assertEqual(override["build"], "24B91016s")

    def test_pick_iphone_devicetype_prefers_newest_standard_iphone(self):
        data = {
            "devicetypes": [
                {"identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-SE-3rd-generation", "name": "iPhone SE (3rd generation)", "productFamily": "iPhone"},
                {"identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16", "name": "iPhone 16", "productFamily": "iPhone"},
                {"identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-17", "name": "iPhone 17", "productFamily": "iPhone"},
                {"identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro-Max", "name": "iPhone 17 Pro Max", "productFamily": "iPhone"},
                {"identifier": "com.apple.CoreSimulator.SimDeviceType.iPad-Pro", "name": "iPad Pro", "productFamily": "iPad"},
            ]
        }
        self.assertEqual(
            self.mod.pick_iphone_devicetype(data),
            "com.apple.CoreSimulator.SimDeviceType.iPhone-17",
        )

    def test_verify_local_cache_detects_ok_and_corruption(self):
        cache = self.root / "cache"
        xcode_file = cache / "xcode/Xcode-27.2-27B52.cpio.zst"
        rt_file = cache / "runtimes/iOS-27.2-24B8117/Restore/runtime.dmg"

        x_sha, x_size = self.mod.stream_and_hash_to_file(io.BytesIO(b"xcode-bytes"), xcode_file)
        r_sha, r_size = self.mod.stream_and_hash_to_file(io.BytesIO(b"runtime-bytes"), rt_file)
        self.assertEqual(x_sha, hashlib.sha256(b"xcode-bytes").hexdigest())

        self.mod.write_manifest_atomic(
            cache,
            {
                "schema": 1,
                "xcode": {
                    "version": "27.2",
                    "build": "27B52",
                    "archive": "xcode/Xcode-27.2-27B52.cpio.zst",
                    "sha256": x_sha,
                    "size_bytes": x_size,
                },
                "ios_runtime": {
                    "version": "27.2",
                    "build": "24B8117",
                    "dmg_relpath": "runtimes/iOS-27.2-24B8117/Restore/runtime.dmg",
                    "files": [
                        {
                            "path": "runtimes/iOS-27.2-24B8117/Restore/runtime.dmg",
                            "sha256": r_sha,
                            "size_bytes": r_size,
                        }
                    ],
                },
            },
        )
        ok, errors = self.mod.verify_local_cache(cache)
        self.assertTrue(ok, errors)

        rt_file.write_bytes(b"corrupted-123")
        ok, errors = self.mod.verify_local_cache(cache)
        self.assertFalse(ok)
        self.assertTrue(any("SHA-256 mismatch" in e for e in errors))

    def test_purge_safety_guards(self):
        mac = {
            "clt_installed": True,
            "clt_path": "/Library/Developer/CommandLineTools",
            "xcode_installed": True,
            "xcode": {"version": "27.2", "build": "27B52"},
            "chosen_ios_runtime": {"version": "27.2", "build": "24B8117"},
        }
        # Missing manifest blocks purge
        self.assertTrue(self.mod.check_purge_safety(mac, None))
        # Matching manifest allows purge
        good_manifest = {
            "xcode": {"version": "27.2", "build": "27B52", "sha256": "abc"},
            "ios_runtime": {"version": "27.2", "build": "24B8117", "files": [{"path": "x"}]},
        }
        self.assertEqual(self.mod.check_purge_safety(mac, good_manifest), [])
        # Missing CLT blocks even with --force unless --keep-xcode
        mac_no_clt = dict(mac, clt_installed=False)
        self.assertTrue(self.mod.check_purge_safety(mac_no_clt, good_manifest, force=True))
        self.assertEqual(self.mod.check_purge_safety(mac_no_clt, good_manifest, force=True, keep_xcode=True), [])

    def test_privileged_prefix_selection(self):
        enrolled = self.root / "enrolled"
        enrolled.write_text("enrolled\n")
        self.assertEqual(self.mod.privileged_prefix(euid=0, enrolled_path=enrolled), [])
        self.assertEqual(
            self.mod.privileged_prefix(euid=501, enrolled_path=enrolled, which_fn=lambda _: "/usr/bin/brick-admin"),
            ["brick-admin", "run"],
        )
        self.assertEqual(
            self.mod.privileged_prefix(euid=501, enrolled_path=self.root / "missing", which_fn=lambda _: "/usr/bin/brick-admin"),
            ["sudo"],
        )


if __name__ == "__main__":
    unittest.main()
