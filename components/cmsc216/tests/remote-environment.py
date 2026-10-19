#!/usr/bin/env python3
"""Execute generated SSH commands against a deliberately polluted environment."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

BASH = shutil.which("bash")
ENV = shutil.which("env")
PRINTF = shutil.which("printf")
PWD = shutil.which("pwd")
CLI = str(Path(sys.argv.pop(1)).resolve())


class RemoteEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "course with 'quotes' and $dollars"
        self.directory.mkdir()
        self.env = dict(os.environ, CMSC216_DIRECTORY_ID="test-user",
                        CMSC216_LOCAL_ROOT=str(self.directory),
                        CMSC216_REMOTE_ROOT=str(self.directory),
                        CMSC216_DATA_ROOT=str(self.root / "data"),
                        CMSC216_CODIUM_BIN="/bin/true",
                        CMSC216_REMOTE_ENVIRONMENT="system")

    def generate(self, *args, mode="system"):
        env = dict(self.env, CMSC216_REMOTE_ENVIRONMENT=mode)
        return subprocess.check_output(
            ["bash", "-c", 'cli="$1"; shift; source "$cli" help >/dev/null; '
             'build_remote_command "$@"', "test", CLI, str(self.directory), *args],
            env=env, text=True).strip()

    def execute_polluted(self, command):
        command = command.replace("/bin/bash", BASH, 1).replace("/usr/bin/env", ENV, 1)
        poison = self.root / "startup"
        poison.write_text("echo UNEXPECTED_STARTUP >&2; exit 99\n")
        # Export after Bash has started, just like the course's startup files.
        return subprocess.run(
            ["bash", "-c", 'export BASH_ENV="$2" ENV="$2" '
             'GCC_EXEC_PREFIX=/unavailable/cvmfs PYTHONHOME=/unavailable/cvmfs '
             'LD_LIBRARY_PATH=/unavailable/cvmfs; '
             'export PATH=/unavailable/cvmfs; eval "$1"', "test", command, str(poison)],
            env=self.env, text=True, capture_output=True, check=True)

    def test_system_discards_module_and_startup_environment(self):
        result = self.execute_polluted(self.generate(ENV))
        values = dict(line.split("=", 1) for line in result.stdout.splitlines())
        for name in ("GCC_EXEC_PREFIX", "PYTHONHOME", "BASH_ENV", "ENV", "LD_LIBRARY_PATH"):
            self.assertNotIn(name, values)
        self.assertEqual(values["PATH"], "/usr/bin:/bin")
        self.assertEqual(values["PARALLEL"], "8")
        self.assertEqual(values["HOME"], self.env["HOME"])
        self.assertEqual(result.stderr, "")

    def test_preserves_arguments_and_working_directory(self):
        payload = "space 'quote' $HOME `false` ; \nnext line"
        result = self.execute_polluted(self.generate(PRINTF, "%s", payload))
        self.assertEqual(result.stdout, payload)
        result = self.execute_polluted(self.generate(PWD))
        self.assertEqual(result.stdout.strip(), str(self.directory))

    def test_preserves_private_course_permissions(self):
        result = self.execute_polluted(self.generate(BASH, "--noprofile", "--norc", "-c", "umask"))
        self.assertEqual(result.stdout.strip(), "0077")

    def test_course_mode_preserves_existing_environment(self):
        command = self.generate(ENV, mode="course")
        result = subprocess.check_output(["bash", "-c", command],
                                         env=dict(self.env, COURSE_MARKER="preserved"), text=True)
        self.assertIn("COURSE_MARKER=preserved", result.splitlines())
        self.assertNotIn("env -i", command)

    def capture_ssh(self, action):
        log = self.root / "ssh-command"
        ssh = self.root / "ssh"
        ssh.write_text('#!' + BASH + '\nprintf "%s\\n" "${@: -1}" > "$SSH_LOG"\n')
        ssh.chmod(0o755)
        env = dict(self.env, HOME=str(self.root / "home"),
                   CMSC216_SSH_BIN=str(ssh), SSH_LOG=str(log))
        subprocess.run(["bash", CLI, action], env=env, check=True, capture_output=True)
        return log.read_text()

    def test_shell_bypasses_login_startup(self):
        command = self.capture_ssh("shell")
        self.assertIn("--noprofile", command)
        self.assertIn("--norc", command)
        self.assertNotIn("bash -l", command)
        self.assertIn("env -i", command)

    def test_rsync_forwards_server_arguments(self):
        command = subprocess.check_output(
            ["bash", "-c", 'source "$1" help >/dev/null; remote_rsync_command', "test", CLI],
            env=self.env, text=True).strip()
        rsync = self.root / "rsync"
        rsync.write_text("#!" + BASH + "\n" + 'printf "%s\\n" "$@"\n')
        rsync.chmod(0o755)
        command = command.replace("PATH=/usr/bin:/bin", "PATH=" + str(self.root))
        result = self.execute_polluted(command + " --server --sender . 'directory with spaces'")
        self.assertEqual(result.stdout.splitlines(), ["--server", "--sender", ".", "directory with spaces"])

    def test_sync_uses_isolated_rsync(self):
        rsync = self.root / "rsync"
        log = self.root / "rsync-args"
        rsync.write_text('#!' + BASH + '\nprintf "%s\\n" "$@" > "$RSYNC_LOG"\n')
        rsync.chmod(0o755)
        ssh = self.root / "ssh"
        ssh.write_text("#!" + BASH + "\nexit 0\n")
        ssh.chmod(0o755)
        subprocess.run(["bash", CLI, "sync"], check=True, capture_output=True,
                       env=dict(self.env, HOME=str(self.root / "home"),
                                PATH=str(self.root) + ":" + os.environ["PATH"],
                                CMSC216_SSH_BIN=str(ssh), RSYNC_LOG=str(log)))
        remote = next(arg.removeprefix("--rsync-path=") for arg in log.read_text().splitlines()
                      if arg.startswith("--rsync-path="))
        self.assertIn("env -i", remote)
        self.assertIn("rsync", remote)
        self.assertNotIn("--delete", log.read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
