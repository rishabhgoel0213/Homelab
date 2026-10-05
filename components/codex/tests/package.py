"""Validate the complete installed archive and initialize voice without devices."""

import json
import os
import plistlib
from pathlib import Path
import select
import stat
import struct
import subprocess
import sys
import tarfile
import time


def verify_archive(archive_path, package):
    count = 0
    with tarfile.open(archive_path) as archive:
        for member in archive:
            relative = Path(member.name)
            assert not relative.is_absolute() and ".." not in relative.parts, (
                member.name
            )
            installed = package / relative
            if member.isdir():
                assert installed.is_dir(), member.name
            elif member.issym():
                assert installed.is_symlink(), member.name
                assert os.readlink(installed) == member.linkname, member.name
            elif member.isfile() or member.islnk():
                assert installed.is_file(), member.name
                assert (
                    stat.S_IMODE(installed.stat().st_mode) & 0o111
                    == member.mode & 0o111
                ), member.name
                with (
                    archive.extractfile(member) as original,
                    installed.open("rb") as actual,
                ):
                    header = original.read(4)
                    if header == b"\x7fELF":
                        # Nix adjusts ELF interpreters and library search paths.
                        assert actual.read(4) == header, member.name
                    else:
                        assert actual.read(4) == header, member.name
                        while block := original.read(1024 * 1024):
                            assert actual.read(len(block)) == block, member.name
                        assert not actual.read(1), member.name
            else:
                raise AssertionError(f"Unsupported archive member: {member.name}")
            count += 1
    print(f"Verified all {count} upstream archive entries")


def verify_voice(package):
    helper = package / "codex-resources/voice/bin/codex-voice-host"
    commit = subprocess.check_output(
        [helper, "--build-commit"], text=True, timeout=15
    ).strip()
    assert commit and commit != "dev", "Expected the upstream release voice helper"
    environment = os.environ | {
        "GST_PLUGIN_PATH": "",
        "GST_PLUGIN_PATH_1_0": "",
        "GST_PLUGIN_SYSTEM_PATH": "",
        "GST_PLUGIN_SYSTEM_PATH_1_0": "",
        "GST_REGISTRY": "/dev/null",
        "GST_REGISTRY_UPDATE": "no",
        "GST_REGISTRY_FORK": "no",
    }
    with subprocess.Popen(
        [helper], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=environment
    ) as process:

        def read_exact(size):
            data = b""
            deadline = time.monotonic() + 20
            while len(data) < size:
                remaining = max(0, deadline - time.monotonic())
                assert select.select([process.stdout], [], [], remaining)[0], (
                    "Voice helper timed out"
                )
                block = os.read(process.stdout.fileno(), size - len(data))
                assert block, f"Voice helper exited early: {process.poll()}"
                data += block
            return data

        def exchange(message, expected):
            payload = json.dumps(message).encode()
            process.stdin.write(struct.pack(">I", len(payload)) + payload)
            process.stdin.flush()
            length = struct.unpack(">I", read_exact(4))[0]
            assert length <= 128 * 1024, length
            assert json.loads(read_exact(length)) == {"type": expected}

        try:
            exchange({"type": "hello", "protocol": 1, "buildCommit": commit}, "ready")
            exchange({"type": "initializeRuntime"}, "runtimeReady")
            exchange({"type": "close"}, "closed")
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.kill()
    print(
        "Voice helper and bundled audio runtime initialized (no device or network access)"
    )


def main():
    archive, destination, version, target = sys.argv[1:5]
    package = Path(destination).resolve()
    verify_archive(archive, package)
    metadata = json.loads((package / "codex-package.json").read_text())
    assert metadata["layoutVersion"] == 1
    assert metadata["version"] == version
    assert metadata["target"] == target
    assert metadata["variant"] == "codex"
    assert metadata["entrypoint"] == "bin/codex"
    assert metadata["resourcesDir"] == "codex-resources"
    assert metadata["pathDir"] == "codex-path"
    if sys.argv[5:] == ["--mac-archive"]:
        bundle = package / "CodexCLI.app/Contents"
        info = plistlib.loads((bundle / "Info.plist").read_bytes())
        assert info["CFBundleIdentifier"] == "com.openai.codex.cli"
        assert (bundle / "_CodeSignature/CodeResources").is_file()
        assert (package / "codex-resources/voice/bin/codex-voice-host").is_file()
        assert (
            package / "codex-resources/voice/lib/libgstreamer-1.0.0.dylib"
        ).is_file()
        print(
            "Verified complete signed Mac archive; native execution awaits Mac deployment"
        )
        return
    actual = subprocess.check_output(
        [package / "bin/codex", "--version"], text=True, timeout=15
    )
    assert actual.strip() == f"codex-cli {version}", actual
    verify_voice(package)


if __name__ == "__main__":
    main()
