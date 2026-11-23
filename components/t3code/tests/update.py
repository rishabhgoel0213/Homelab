"""Exercise pin rollback and reject malformed release metadata offline."""
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest


class UpdateTest(unittest.TestCase):
    def run_update(self, target, build_status=0, apk_count=1):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package.nix"
            manifest = root / "artifacts.nix"
            original = 'version = "0.1.7-nightly.20261103.4100";\n'
            original += 'linuxHash = "sha256-' + 'A' * 43 + '=";\n'
            original += 'macHash = "sha256-' + 'E' * 43 + '=";\n'
            original += 'mobileApkName = "t3code-android-internal-2.1.0-700.apk";\n'
            original += 'mobileApkHash = "sha256-' + 'D' * 43 + '=";\n'
            package.write_text(original)
            old_store = "/nix/store/" + "0" * 32 + "-t3code-darwin-0.1.7-nightly.20261103.4100"
            new_store = "/nix/store/" + "1" * 32 + "-t3code-darwin-0.1.8-nightly.20261104.4179"
            original_manifest = f'{{\n  t3code = "{old_store}";\n}}\n'
            manifest.write_text(original_manifest)
            nix = root / "nix"
            nix.write_text(
                "#!" + shutil.which("bash") + "\n"
                'if [[ "$1" == store ]]; then\n'
                '  if [[ "$*" == *.apk ]]; then\n'
                '    echo \'{"hash":"sha256-' + 'C' * 43 + '="}\'\n'
                '  elif [[ "$*" == *darwin-arm64.tar.gz ]]; then\n'
                '    echo \'{"hash":"sha256-' + 'F' * 43 + '="}\'\n'
                "  else\n"
                '    echo \'{"hash":"sha256-' + 'B' * 43 + '="}\'\n'
                "  fi\n"
                'elif [[ "$*" == *macbook-t3code* ]]; then\n'
                f'  echo "{new_store}"\n'
                "else\n"
                f"  exit {build_status}\n"
                "fi\n"
            )
            nix.chmod(0o755)
            curl = root / "curl"
            assets = ",".join('{"name":"t3code-android-internal-2.2.0-741.apk"}' for _ in range(apk_count))
            curl.write_text("#!" + shutil.which("bash") + '\necho \'{"assets":[' + assets + "]}\'\n")
            curl.chmod(0o755)
            result = subprocess.run(
                ["bash", os.environ["T3CODE_UPDATE_SCRIPT"], target],
                env={
                    **os.environ,
                    "PATH": str(root) + ":" + os.environ["PATH"],
                    "T3CODE_OPS_ROOT": tmp,
                    "T3CODE_PACKAGE_FILE": str(package),
                    "T3CODE_ARTIFACT_FILE": str(manifest),
                },
                capture_output=True,
                text=True,
            )
            return result, package.read_text(), original, manifest.read_text(), original_manifest, new_store

    def test_failed_build_restores_entire_pin(self):
        result, actual, original, actual_manifest, original_manifest, _ = self.run_update(
            "0.1.8-nightly.20261104.4179", 42
        )
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(actual, original)
        self.assertEqual(actual_manifest, original_manifest)

    def test_success_updates_version_hashes_and_manifest(self):
        result, actual, _, actual_manifest, _, new_store = self.run_update("0.1.8-nightly.20261104.4179")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('version = "0.1.8-nightly.20261104.4179";', actual)
        self.assertIn('linuxHash = "sha256-' + "B" * 43 + '=";', actual)
        self.assertIn('macHash = "sha256-' + "F" * 43 + '=";', actual)
        self.assertIn('mobileApkName = "t3code-android-internal-2.2.0-741.apk";', actual)
        self.assertIn('mobileApkHash = "sha256-' + "C" * 43 + '=";', actual)
        self.assertIn(f't3code = "{new_store}";', actual_manifest)

    def test_missing_apk_keeps_server_and_phone_pins_unchanged(self):
        result, actual, original, actual_manifest, original_manifest, _ = self.run_update(
            "0.1.8-nightly.20261104.4179", apk_count=0
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(actual, original)
        self.assertEqual(actual_manifest, original_manifest)

    def test_ambiguous_apks_keep_pins_unchanged(self):
        result, actual, original, actual_manifest, original_manifest, _ = self.run_update(
            "0.1.8-nightly.20261104.4179", apk_count=2
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(actual, original)
        self.assertEqual(actual_manifest, original_manifest)

    def test_invalid_version_leaves_pin_untouched(self):
        result, actual, original, actual_manifest, original_manifest, _ = self.run_update('0.1.8"; malicious')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(actual, original)
        self.assertEqual(actual_manifest, original_manifest)


if __name__ == "__main__":
    unittest.main()
