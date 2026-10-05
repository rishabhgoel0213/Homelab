"""Mac-side Codex selection, signed updates, and a private SSH remote UI tunnel."""

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading


STORE_PATH = re.compile(
    r"/nix/store/[a-z0-9]{32}-codex-darwin-bundle-([0-9]+\.[0-9]+\.[0-9]+)"
)

# Run via the authenticated SSH user's Python, not a root-owned socket-forward
# handler. Only bytes cross SSH; audio is captured/played by the native Mac TUI.
REMOTE_RELAY = r"""
import os, socket, sys, threading
s = socket.socket(socket.AF_UNIX)
s.connect(sys.argv[1])
def upload():
    try:
        while data := os.read(0, 65536):
            s.sendall(data)
    except OSError:
        pass
    finally:
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
threading.Thread(target=upload, daemon=True).start()
try:
    while data := s.recv(65536):
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
finally:
    s.close()
"""


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
            raise RuntimeError(f"Unexpected Codex profile: {package}")
        return package
    return Path(config["bootstrap"])


def validate_release(release):
    match = STORE_PATH.fullmatch(release.get("storePath", ""))
    if (
        release.get("schema") != 1
        or release.get("target") != "aarch64-apple-darwin"
        or not match
        or release.get("version") != match[1]
    ):
        raise RuntimeError("Invalid server Codex release manifest")
    return Path(release["storePath"])


def verify_mac(package, version):
    metadata = json.loads((package / "codex-package.json").read_text())
    if (
        metadata.get("version") != version
        or metadata.get("target") != "aarch64-apple-darwin"
    ):
        raise RuntimeError("Downloaded package does not match the published release")
    execute(
        [
            "/usr/bin/codesign",
            "--verify",
            "--deep",
            "--strict",
            str(package / "CodexCLI.app"),
        ]
    )
    # Check every Mach-O file, including nested voice libraries and future helpers.
    magic = {
        b"\xcf\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
    }
    for path in package.rglob("*"):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                if stream.read(4) in magic:
                    execute(["/usr/bin/codesign", "--verify", "--strict", str(path)])
    actual = output([str(package / "bin/codex"), "--version"])
    if actual != f"codex-cli {version}":
        raise RuntimeError(f"Unexpected Codex version: {actual}")


def update(config):
    state = Path(config["stateDir"])
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / "update.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another Codex update is running.")
            return
        release = json.loads(
            output(ssh_args(config) + [config["sshHost"], "cat", config["releaseFile"]])
        )
        package = validate_release(release)
        current = selected_package(config)
        if current == package:
            print(f"Codex is current at {release['version']}.")
            return
        current_version = json.loads((current / "codex-package.json").read_text())[
            "version"
        ]
        if tuple(map(int, release["version"].split("."))) < tuple(
            map(int, current_version.split("."))
        ):
            raise RuntimeError("Refusing an automatic Codex downgrade")
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
            f"Installed Codex {release['version']}. New terminal sessions will use it."
        )


def server(config, arguments):
    # Keep the socket short enough for Darwin's Unix-domain socket path limit.
    temporary = tempfile.mkdtemp(prefix="codex-server-", dir="/tmp")
    local_socket = Path(temporary) / "agent.sock"
    command = ssh_args(config) + [
        "-T",
        "-o",
        "ClearAllForwardings=yes",
        config["sshHost"],
        shlex.join(
            [
                "/run/current-system/sw/bin/python3",
                "-c",
                REMOTE_RELAY,
                config["remoteSocket"],
            ]
        ),
    ]
    children = set()
    children_lock = threading.Lock()

    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            with children_lock:
                child = subprocess.Popen(
                    command, stdin=self.request, stdout=self.request
                )
                children.add(child)
            try:
                child.wait()
            finally:
                with children_lock:
                    children.discard(child)

    class Listener(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True
        block_on_close = False

    tunnel = Listener(str(local_socket), Relay)
    os.chmod(local_socket, 0o600)
    worker = threading.Thread(target=tunnel.serve_forever, daemon=True)
    worker.start()
    client = None
    old_interrupt = signal.signal(signal.SIGINT, lambda *_: None)
    try:
        # Remote mode keeps cwd, tools, authentication and history on the server.
        # Do not inject the Mac cwd as a server project path.
        cli = str(selected_package(config) / "bin/codex")
        client = subprocess.Popen(
            [cli, "--remote", f"unix://{local_socket}", *arguments]
        )
        return client.wait()
    finally:
        signal.signal(signal.SIGINT, old_interrupt)
        if client is not None and client.poll() is None:
            client.terminate()
            try:
                client.wait(timeout=5)
            except subprocess.TimeoutExpired:
                client.kill()
                client.wait()
        tunnel.shutdown()
        tunnel.server_close()
        worker.join()
        with children_lock:
            remaining = list(children)
        for child in remaining:
            with contextlib.suppress(ProcessLookupError):
                child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("action", choices=["update", "server", "run"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    arguments = options.arguments
    config = json.loads(Path(options.config).read_text())
    if options.action == "update":
        if arguments:
            parser.error("update takes no arguments")
        update(config)
    elif options.action == "server":
        return server(config, arguments)
    else:
        cli = str(selected_package(config) / "bin/codex")
        os.execv(cli, [cli, *arguments])
    return 0


if __name__ == "__main__":
    # Cleanup the tunnel when the terminal closes; normal Ctrl-C is delivered
    # to Codex too, and the finally block reaps the SSH child.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    signal.signal(signal.SIGHUP, lambda *_: sys.exit(129))
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"codex: {error}", file=sys.stderr)
        sys.exit(1)
