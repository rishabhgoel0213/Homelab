"""Mac Antigravity launcher and verified signed-profile updates."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys


STORE_PATH = re.compile(
    r"/nix/store/[a-z0-9]{32}-antigravity-cli-darwin-([0-9]+\.[0-9]+\.[0-9]+)"
)

def execute(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(args):
    return subprocess.check_output(args, text=True, timeout=45).strip()


def ssh_args(config):
    return [
        config["ssh"],
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
    ]


def selected_package(config):
    profile = Path(config["stateDir"]) / "profile"
    if profile.exists():
        package = profile.resolve()
        if not STORE_PATH.fullmatch(str(package)):
            raise RuntimeError(f"Unexpected Antigravity profile: {package}")
        return package
    return Path(config["bootstrap"])


def validate_release(release):
    match = STORE_PATH.fullmatch(release.get("storePath", ""))
    if (
        release.get("schema") != 1
        or release.get("target") != "darwin-arm64"
        or not match
        or release.get("version") != match[1]
    ):
        raise RuntimeError("Invalid server Antigravity release manifest")
    return Path(release["storePath"])


def verify_mac(package, version):
    metadata = json.loads((package / "antigravity-package.json").read_text())
    if (
        metadata.get("version") != version
        or metadata.get("target") != "darwin-arm64"
    ):
        raise RuntimeError("Downloaded package does not match the published release")
    execute(["/usr/bin/codesign", "--verify", "--strict", str(package / "bin/agy")])
    actual = output([str(package / "bin/agy"), "--version"])
    # agy prints only the bare version number.
    if actual != version:
        raise RuntimeError(f"Unexpected Antigravity version: {actual}")


def update(config):
    state = Path(config["stateDir"])
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / "update.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another Antigravity update is running.")
            return
        release = json.loads(
            output(ssh_args(config) + [config["sshHost"], "cat", config["releaseFile"]])
        )
        package = validate_release(release)
        current = selected_package(config)
        if current == package:
            print(f"Antigravity is current at {release['version']}.")
            return
        current_version = json.loads((current / "antigravity-package.json").read_text())[
            "version"
        ]
        if tuple(map(int, release["version"].split("."))) < tuple(
            map(int, current_version.split("."))
        ):
            raise RuntimeError("Refusing an automatic Antigravity downgrade")
        environment = os.environ | {
            "NIX_SSHOPTS": "-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes"
        }
        execute(
            [
                config["nix"],
                "copy",
                "--from",
                f"ssh-ng://{config['sshHost']}",
                str(package),
            ],
            env=environment,
            timeout=900,
        )
        # A temporary profile roots the candidate while checking native signing.
        # It is never selected by the launcher; failed verification leaves the
        # active profile untouched. Future attempts replace this candidate root.
        execute(
            [
                config["nixEnv"],
                "--profile",
                str(state / "candidate"),
                "--set",
                str(package),
            ],
            timeout=60,
        )
        execute(
            [
                config["nix"],
                "store",
                "verify",
                "--sigs-needed",
                "1",
                "--trusted-public-keys",
                config["publicKey"],
                str(package),
            ],
            timeout=120,
        )
        verify_mac(package, release["version"])
        # nix-env switches the dedicated user profile atomically and retains
        # generations/GC roots. Existing processes continue using their old binary.
        execute(
            [
                config["nixEnv"],
                "--profile",
                str(state / "profile"),
                "--set",
                str(package),
            ],
            timeout=60,
        )
        print(
            f"Installed Antigravity {release['version']}. New terminal sessions will use it."
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("action", choices=["update", "run"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    arguments = options.arguments
    config = json.loads(Path(options.config).read_text())
    if options.action == "update":
        if arguments:
            parser.error("update takes no arguments")
        update(config)
    else:
        cli = str(selected_package(config) / "bin/agy")
        os.execv(cli, [cli, *arguments])
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    signal.signal(signal.SIGHUP, lambda *_: sys.exit(129))
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"agy: {error}", file=sys.stderr)
        sys.exit(1)
