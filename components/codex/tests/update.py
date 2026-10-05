"""Offline regression checks for complete-package updates and failed installs."""

import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


COMPONENT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "package_check", COMPONENT / "tests/package.py"
)
package_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_check)
OLD_HASH = "sha256-" + "A" * 43 + "="
NEW_HASH = "sha256-" + "B" * 43 + "="


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "package.nix"
        self.original = (
            'version = "0.160.0";\n'
            f'archiveHash = "{OLD_HASH}";\n'
            'target = "x86_64-unknown-linux-musl";\n'
            'macTarget = "aarch64-apple-darwin";\n'
            f'macArchiveHash = "{OLD_HASH}";\n'
            "# Preserve unrelated configuration.\n"
        )
        self.package.write_text(self.original)
        self.manifest = self.root / "artifacts.nix"
        self.original_manifest = '{ codex = "/nix/store/old-codex"; }\n'
        self.manifest.write_text(self.original_manifest)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        self.stub(
            "git",
            "printf '%s\\n' 'abc refs/tags/rust-v0.161.0' 'abc refs/tags/rust-v0.162.0-alpha.1' 'abc refs/tags/rust-v0.160.0'",
        )
        self.stub(
            "nix",
            """
printf '%s\\n' "$*" >> "$TEST_CALLS"
if [[ "$1" == store ]]; then
  [[ "${TEST_FAIL_FETCH:-0}" == 0 ]] || exit 1
  if [[ "${TEST_FAIL_MAC_FETCH:-0}" == 1 && "$*" == *apple-darwin* ]]; then exit 1; fi
  printf '{"hash":"%s"}\\n' "$TEST_HASH"
else
  if [[ "$*" == *macbook-codex* ]]; then
    echo /nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-codex-darwin-bundle-0.161.0
  fi
  if [[ "${TEST_CONCURRENT_EDIT:-0}" == 1 ]]; then
    printf '# Concurrent edit\\n' >> "$CODEX_PACKAGE_FILE"
  fi
  [[ "${TEST_FAIL_BUILD:-0}" == 0 ]] || exit 1
  if [[ "${TEST_FAIL_HOST_BUILD:-0}" == 1 && "$*" == *nixosConfigurations* ]]; then exit 1; fi
fi
""",
        )

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{shutil.which('bash')}\nset -euo pipefail\n" + body + "\n")
        path.chmod(0o755)

    def run_update(self, target="latest", **extra):
        environment = (
            os.environ
            | {
                "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                "CODEX_OPS_ROOT": str(self.root),
                "CODEX_PACKAGE_FILE": str(self.package),
                "CODEX_ARTIFACT_FILE": str(self.manifest),
                "CODEX_UPDATE_FORCE": "0",
                "HOST": "test-host",
                "TEST_CALLS": str(self.calls),
                "TEST_HASH": NEW_HASH,
            }
            | extra
        )
        return subprocess.run(
            ["bash", COMPONENT / "bin/update", target],
            env=environment,
            text=True,
            capture_output=True,
            timeout=20,
        )

    def test_latest_fetches_both_complete_archives_and_builds_before_success(self):
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.package.read_text(),
            self.original.replace("0.160.0", "0.161.0").replace(OLD_HASH, NEW_HASH),
        )
        self.assertEqual(
            self.calls.read_text().splitlines(),
            [
                "store prefetch-file --json https://github.com/openai/codex/releases/download/rust-v0.161.0/codex-package-x86_64-unknown-linux-musl.tar.gz",
                "store prefetch-file --json https://github.com/openai/codex/releases/download/rust-v0.161.0/codex-provisioned-package-aarch64-apple-darwin.tar.gz",
                "build --impure --no-link --print-out-paths .#macbook-codex",
                "build --impure --no-link .#nixosConfigurations.test-host.config.system.build.toplevel",
            ],
        )

    def test_current_version_is_noop(self):
        result = self.run_update("0.160.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.calls.exists())
        self.assertEqual(self.package.read_text(), self.original)

    def test_force_revalidates_current_version(self):
        result = self.run_update("0.160.0", CODEX_UPDATE_FORCE="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("build --impure --no-link", self.calls.read_text())

    def test_missing_archive_leaves_pin_unchanged(self):
        result = self.run_update(TEST_FAIL_FETCH="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.package.read_text(), self.original)
        self.assertNotIn("build", self.calls.read_text())

    def test_failed_build_restores_pin_and_can_retry(self):
        result = self.run_update(TEST_FAIL_BUILD="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.package.read_text(), self.original)
        self.assertEqual(self.manifest.read_text(), self.original_manifest)
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('version = "0.161.0";', self.package.read_text())

    def test_failed_host_build_restores_both_pins(self):
        result = self.run_update(TEST_FAIL_HOST_BUILD="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.package.read_text(), self.original)
        self.assertEqual(self.manifest.read_text(), self.original_manifest)

    def test_missing_mac_archive_leaves_both_pins_unchanged(self):
        result = self.run_update(TEST_FAIL_MAC_FETCH="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.package.read_text(), self.original)
        self.assertEqual(self.manifest.read_text(), self.original_manifest)
        self.assertNotIn("build", self.calls.read_text())

    def test_concurrent_edit_is_preserved(self):
        result = self.run_update(TEST_FAIL_BUILD="1", TEST_CONCURRENT_EDIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.package.read_text().endswith("# Concurrent edit\n"))

    def test_invalid_release_or_hash_never_changes_pin(self):
        for target, extra in [
            ("0.161.0-beta", {}),
            ("0.161.0", {"TEST_HASH": "invalid"}),
        ]:
            with self.subTest(target=target):
                self.assertNotEqual(self.run_update(target, **extra).returncode, 0)
                self.assertEqual(self.package.read_text(), self.original)


class InventoryTests(unittest.TestCase):
    def test_future_bundle_must_survive_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "release.tar.gz"
            member = "codex-resources/future-feature/data.json"
            payload = json.dumps({"new": "bundle"}).encode()
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo(member)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            package = root / "installed"
            installed = package / member
            installed.parent.mkdir(parents=True)
            with self.assertRaises(AssertionError):
                package_check.verify_archive(archive_path, package)
            installed.write_bytes(payload)
            package_check.verify_archive(archive_path, package)
            installed.write_bytes(b"corrupt")
            with self.assertRaises(AssertionError):
                package_check.verify_archive(archive_path, package)


if __name__ == "__main__":
    unittest.main()
