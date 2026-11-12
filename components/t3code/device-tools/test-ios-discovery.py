"""Exercise the packaged hub without Xcode, a real simulator, or Android SDK."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request


def main():
    node, cli = sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix="t3-ios-discovery-") as directory:
        root = Path(directory)
        device_id = "11111111-2222-3333-4444-555555555555"
        fixture = {
            "devices": {
                "com.apple.CoreSimulator.SimRuntime.iOS-27-2": [
                    {
                        "udid": device_id,
                        "name": "Fresh Hackathon iPhone",
                        "state": "Shutdown",
                        "isAvailable": True,
                        "deviceTypeIdentifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-18-Pro",
                    },
                    {
                        "udid": "unavailable-device",
                        "name": "Unavailable iPhone",
                        "state": "Shutdown",
                        "isAvailable": False,
                    },
                ]
            }
        }
        (root / "devices.json").write_text(json.dumps(fixture))
        xcrun = root / "xcrun"
        xcrun.write_text(
            "#!/bin/sh\n"
            'test "$*" = "simctl list devices --json" || exit 91\n'
            'cat "$HUB_TEST_ROOT/devices.json"\n'
        )
        xcrun.chmod(0o755)
        for command in ("adb", "emulator", "avdmanager", "sdkmanager"):
            stub = root / command
            stub.write_text(
                '#!/bin/sh\necho "$0 $*" >> "$HUB_TEST_ROOT/android-called"\nexit 92\n'
            )
            stub.chmod(0o755)
        env = dict(os.environ, HOME=str(root), HUB_TEST_ROOT=str(root))
        env["PATH"] = str(root) + os.pathsep + env["PATH"]
        with (root / "hub.log").open("w+") as log:
            # No --platform: exercise the default used by T3's SSH launcher.
            process = subprocess.Popen(
                [node, cli, "--host", "127.0.0.1", "--port", "0", "--hide-sidebar"],
                env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    log.seek(0)
                    output = log.read()
                    match = re.search(r"https?://(?:localhost|127\.0\.0\.1):(\d+)", output)
                    if match:
                        break
                    if process.poll() is not None:
                        raise AssertionError(f"Hub exited before listening:\n{output}")
                    time.sleep(0.1)
                else:
                    raise AssertionError(f"Hub never started:\n{output}")
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{match[1]}/api/devices", timeout=10
                ) as response:
                    devices = json.load(response)
                assert [d["id"] for d in devices["simulators"]] == [device_id], devices
                assert devices["simulators"][0]["booted"] is False, devices
                assert devices["emulators"] == [], devices
                assert devices["errors"] == [], devices
                assert not (root / "android-called").exists(), "Android discovery ran"
                print("iOS-only discovery: fresh simulator visible; no Android probes")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
