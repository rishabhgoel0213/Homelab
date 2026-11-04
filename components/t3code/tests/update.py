"""Exercise pin rollback and reject malformed release metadata offline."""
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest


class UpdateTest(unittest.TestCase):
    def run_update(self, target, build_status=0):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package.nix"
            original = 'version = "0.1.7-nightly.20261103.4100";\nhash = "sha256-' + 'A' * 43 + '=";\n'
            package.write_text(original)
            nix = root / "nix"
            nix.write_text('#!' + shutil.which('bash') + '\nif [[ "$1" == store ]]; then\n  echo \'{"hash":"sha256-' + 'B' * 43 + '="}\'\nelse\n  exit ' + str(build_status) + '\nfi\n')
            nix.chmod(0o755)
            result = subprocess.run(
                ["bash", os.environ["T3CODE_UPDATE_SCRIPT"], target],
                env={**os.environ, "PATH": str(root) + ":" + os.environ["PATH"],
                     "T3CODE_OPS_ROOT": tmp, "T3CODE_PACKAGE_FILE": str(package)},
                capture_output=True, text=True,
            )
            return result, package.read_text(), original

    def test_failed_build_restores_entire_pin(self):
        result, actual, original = self.run_update("0.1.8-nightly.20261104.4179", 42)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(actual, original)

    def test_success_updates_version_and_hash(self):
        result, actual, _ = self.run_update("0.1.8-nightly.20261104.4179")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('version = "0.1.8-nightly.20261104.4179";', actual)
        self.assertIn('sha256-' + 'B' * 43 + '=', actual)

    def test_invalid_version_leaves_pin_untouched(self):
        result, actual, original = self.run_update('0.1.8"; malicious')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(actual, original)


if __name__ == "__main__":
    unittest.main()
