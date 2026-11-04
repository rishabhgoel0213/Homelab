"""Offline Git integration tests for publication, deployment, and package updates."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


DEPLOY = Path(os.environ["HOMELAB_DEPLOY_SCRIPT"])
AUTO = Path(os.environ["HOMELAB_AUTO_UPDATE_SCRIPT"])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "development"
        self.deployment = self.root / "deployment"
        self.remote = self.root / "origin.git"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
                        PATH=str(self.bin) + ":" + os.environ["PATH"],
                        HOMELAB_DEV_ROOT=str(self.source), HOMELAB_DEPLOY_ROOT=str(self.deployment),
                        PACKAGE_UPDATE_LOCK_FILE=str(self.root / "lock"), WORKFLOW_CALLS=str(self.calls),
                        HOMELAB_ACTIVE_REVISION_FILE=str(self.root / "active"))
        self.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(self.root, "init", "--initial-branch=main", str(self.source))
        self.identity(self.source)
        (self.source / "config").write_text("base\n")
        package = self.source / "components/pi/package.nix"
        package.parent.mkdir(parents=True)
        package.write_text('version = "1.0.0";\n')
        update = package.parent / "bin/update"
        update.parent.mkdir()
        self.script(update, 'printf \'version = "%s";\\n\' "${1:-2.0.0}" > "$PI_OPS_ROOT/components/pi/package.nix"')
        (self.source / "tools").mkdir()
        self.script(self.source / "tools/deploy", DEPLOY.read_text().split("\n", 1)[1])
        self.git(self.source, "add", ".")
        self.git(self.source, "commit", "-m", "base")
        self.base = self.head(self.source)
        self.git(self.source, "remote", "add", "origin", str(self.remote))
        self.git(self.source, "push", "-u", "origin", "main")
        self.git(self.root, "clone", str(self.remote), str(self.deployment))
        self.identity(self.deployment)
        self.script(self.bin / "just", '\n'.join([
            'printf "%s:%s\\n" "$PWD" "$*" >> "$WORKFLOW_CALLS"',
            '[[ "$*" != "${FAIL_STEP:-never}" ]] || exit 42',
            'if [[ "$*" == switch ]]; then git rev-parse HEAD > "$HOMELAB_ACTIVE_REVISION_FILE"; fi',
        ]))

    def script(self, path, body):
        path.write_text(f"#!{shutil.which('bash')}\nset -euo pipefail\n{body}\n")
        path.chmod(0o755)

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), *args], env=self.env,
                              capture_output=True, text=True, check=True).stdout.strip()

    def identity(self, repo):
        self.git(repo, "config", "user.name", "Workflow test")
        self.git(repo, "config", "user.email", "workflow@example.invalid")

    def head(self, repo):
        return self.git(repo, "rev-parse", "HEAD")

    def change(self, repo):
        (repo / "config").write_text("new configuration\n")
        self.git(repo, "add", "config")
        self.git(repo, "commit", "-m", "configuration change")
        return self.head(repo)

    def run_deploy(self, **env):
        return subprocess.run(["bash", str(DEPLOY)], env=self.env | env,
                              capture_output=True, text=True)

    def run_auto(self, version="2.0.0"):
        return subprocess.run(["bash", str(AUTO), "pi", version], env=self.env,
                              capture_output=True, text=True)

    def test_publishes_and_deploys_the_same_commit(self):
        revision = self.change(self.source)
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.head(self.remote), revision)
        self.assertEqual(self.head(self.deployment), revision)
        self.assertEqual(self.calls.read_text().splitlines(), [
            f"{self.source}:check", f"{self.source}:build", f"{self.deployment}:switch"])

    def test_dirty_development_is_preserved(self):
        (self.source / "config").write_text("unfinished work")
        result = self.run_deploy()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.source / "config").read_text(), "unfinished work")
        self.assertEqual(self.head(self.remote), self.base)
        self.assertEqual(self.head(self.deployment), self.base)

    def test_dirty_deployment_is_preserved(self):
        self.change(self.source)
        (self.deployment / "config").write_text("deployment edit")
        self.assertNotEqual(self.run_deploy().returncode, 0)
        self.assertEqual((self.deployment / "config").read_text(), "deployment edit")
        self.assertEqual(self.head(self.remote), self.base)

    def test_failed_check_does_not_publish_or_deploy(self):
        self.change(self.source)
        result = self.run_deploy(FAIL_STEP="check")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(self.head(self.remote), self.base)
        self.assertEqual(self.head(self.deployment), self.base)

    def test_unique_deployment_commits_are_preserved(self):
        self.change(self.source)
        self.change(self.deployment)
        self.git(self.deployment, "commit", "--allow-empty", "-m", "unique deployment commit")
        revision = self.head(self.deployment)
        self.assertNotEqual(self.run_deploy().returncode, 0)
        self.assertEqual(self.head(self.deployment), revision)
        self.assertEqual(self.head(self.remote), self.base)

    def test_remote_divergence_is_preserved(self):
        self.change(self.source)
        self.change(self.deployment)
        self.git(self.deployment, "commit", "--allow-empty", "-m", "remote change")
        self.git(self.deployment, "push", "origin", "main")
        revision = self.head(self.remote)
        self.assertNotEqual(self.run_deploy().returncode, 0)
        self.assertEqual(self.head(self.remote), revision)

    def test_failed_activation_can_retry_the_committed_revision(self):
        revision = self.change(self.source)
        self.assertEqual(self.run_deploy(FAIL_STEP="switch").returncode, 42)
        self.assertEqual(self.head(self.remote), revision)
        self.assertEqual(self.head(self.deployment), revision)
        self.assertEqual(self.run_deploy().returncode, 0)

    def test_failed_push_does_not_modify_deployment(self):
        revision = self.change(self.source)
        hook = self.remote / "hooks/pre-receive"
        self.script(hook, 'echo "test push rejection" >&2; exit 1')
        result = self.run_deploy()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.head(self.deployment), self.base)
        self.assertEqual(self.head(self.source), revision)
        hook.unlink()
        self.assertEqual(self.run_deploy().returncode, 0)

    def test_auto_update_commits_then_publishes_and_deploys(self):
        result = self.run_auto()
        self.assertEqual(result.returncode, 0, result.stderr)
        revision = self.head(self.source)
        self.assertNotEqual(revision, self.base)
        self.assertEqual(self.head(self.remote), revision)
        self.assertEqual(self.head(self.deployment), revision)
        self.assertEqual(self.git(self.source, "status", "--porcelain"), "")

    def test_auto_update_defers_while_agent_is_editing(self):
        (self.source / "config").write_text("agent work")
        result = self.run_auto()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.head(self.source), self.base)
        self.assertEqual((self.source / "components/pi/package.nix").read_text(), 'version = "1.0.0";\n')

    def test_auto_update_retries_an_unpublished_commit(self):
        revision = self.change(self.source)
        result = self.run_auto("1.0.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.head(self.source), revision)
        self.assertEqual(self.head(self.remote), revision)
        self.assertEqual(self.head(self.deployment), revision)


if __name__ == "__main__":
    unittest.main()
