"""Mac T3 Code launcher, backend server wrapper, and verified signed-profile updates."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time


STORE_PATH = re.compile(
    r"/nix/store/[a-z0-9]{32}-t3code-darwin-([0-9]+\.[0-9]+\.[0-9]+-nightly\.[0-9]{8}\.[0-9]+)"
)
VERSION_RE = re.compile(
    r"^([0-9]+)\.([0-9]+)\.([0-9]+)-nightly\.([0-9]{8})\.([0-9]+)$"
)


def execute(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(args):
    return subprocess.check_output(args, text=True, timeout=45).strip()


def version_key(version):
    match = VERSION_RE.fullmatch(version)
    if not match:
        raise RuntimeError(f"Unexpected T3 Code version: {version}")
    return tuple(int(part) for part in match.groups())


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
            raise RuntimeError(f"Unexpected T3 Code profile: {package}")
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
        raise RuntimeError("Invalid server T3 Code release manifest")
    return Path(release["storePath"])


def verify_mac(package, version):
    metadata = json.loads((package / "t3code-package.json").read_text())
    if (
        metadata.get("version") != version
        or metadata.get("target") != "darwin-arm64"
    ):
        raise RuntimeError("Downloaded package does not match the published release")
    binary = package / "libexec/t3code/t3"
    execute(["/usr/bin/codesign", "--verify", "--strict", str(binary)])
    actual = output([str(binary), "--version"])
    if actual != f"t3 v{version}":
        raise RuntimeError(f"Unexpected T3 Code version: {actual}")


def update(config):
    state = Path(config["stateDir"])
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / "update.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another T3 Code update is running.")
            return
        release = json.loads(
            output(ssh_args(config) + [config["sshHost"], "cat", config["releaseFile"]])
        )
        package = validate_release(release)
        current = selected_package(config)
        if current == package:
            print(f"T3 Code is current at {release['version']}.")
            return
        current_version = json.loads((current / "t3code-package.json").read_text())[
            "version"
        ]
        if version_key(release["version"]) < version_key(current_version):
            raise RuntimeError("Refusing an automatic T3 Code downgrade")
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
        # generations/GC roots. The running backend keeps active sessions alive
        # until explicitly restarted with t3code-restart.
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
            f"Installed T3 Code {release['version']}. Run 't3code-restart' when ready to restart the server."
        )


def wait_for_tailscale(timeout_seconds=15):
    tailscale = shutil.which("tailscale")
    if not tailscale:
        print(
            "t3code: tailscale CLI not found in PATH; starting without waiting for tailnet.",
            file=sys.stderr,
        )
        return False
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            raw = subprocess.check_output(
                [tailscale, "status", "--json"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            if json.loads(raw).get("BackendState") == "Running":
                return True
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        if time.monotonic() >= deadline:
            print(
                "t3code: Tailscale not ready before startup; proceeding with loopback server.",
                file=sys.stderr,
            )
            return False
        time.sleep(1)


def serve_args(config, binary, arguments):
    args = [
        binary,
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(config["port"]),
        "--base-dir",
        config["dataDir"],
        "--no-browser",
    ]
    if config.get("tailscaleServe"):
        args.extend(
            [
                "--tailscale-serve",
                "--tailscale-serve-port",
                str(config["tailscaleServePort"]),
            ]
        )
    args.extend(arguments)
    return args


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("action", choices=["update", "run", "serve", "restart"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    arguments = options.arguments
    config = json.loads(Path(options.config).read_text())
    if options.action == "update":
        if arguments:
            parser.error("update takes no arguments")
        update(config)
    elif options.action == "restart":
        if arguments:
            parser.error("restart takes no arguments")
        target = f"gui/{os.getuid()}/{config['launchdLabel']}"
        execute(["/bin/launchctl", "kickstart", "-k", target], timeout=30)
        print(f"Restarted {config['launchdLabel']}.")
    elif options.action == "serve":
        Path(config["dataDir"]).mkdir(parents=True, exist_ok=True, mode=0o700)
        os.environ["T3CODE_HOME"] = config["dataDir"]
        os.environ["DISABLE_AUTOUPDATER"] = "1"
        if config.get("tailscaleServe"):
            wait_for_tailscale()
        binary = str(selected_package(config) / "libexec/t3code/t3")
        args = serve_args(config, binary, arguments)
        os.execv(binary, args)
    else:
        os.environ.setdefault("T3CODE_HOME", config["dataDir"])
        os.environ["DISABLE_AUTOUPDATER"] = "1"
        binary = str(selected_package(config) / "libexec/t3code/t3")
        os.execv(binary, [binary, *arguments])
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    signal.signal(signal.SIGHUP, lambda *_: sys.exit(129))
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"t3code: {error}", file=sys.stderr)
        sys.exit(1)
