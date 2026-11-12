import importlib.util
from pathlib import Path
import tempfile
import subprocess
import sys
import json
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ios_setup', Path(__file__).with_name('ios-setup.py'))
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

class SetupTests(unittest.TestCase):
    def test_runtime_selection_ignores_unavailable_and_other_platforms(self):
        runtimes = [
            {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-27-0', 'version': '27.0', 'isAvailable': True},
            {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-28-0', 'version': '28.0', 'isAvailable': False},
            {'identifier': 'com.apple.CoreSimulator.SimRuntime.watchOS-27-0', 'version': '27.0', 'isAvailable': True},
        ]
        result = setup.choose_device(runtimes, [{'identifier': 'phone', 'productFamily': 'iPhone'}])
        self.assertEqual(result, (runtimes[0]['identifier'], 'phone'))

    def test_missing_ios_runtime_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'No available iOS'):
            setup.choose_device([], [])

    def test_gate_failure_prevents_command(self):
        with patch.object(setup, 'gate', side_effect=RuntimeError('bricked')), patch.object(setup.subprocess, 'run') as run:
            with self.assertRaises(RuntimeError): setup.run('command', admin=True)
            run.assert_not_called()

    def test_host_registration_preserves_unrelated_settings_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / 'settings.json'
            host = root / 'host.json'
            original = {'opaque': {'keep': True}, 'deviceHosts': [{'id': 'other', 'target': 'somewhere'}]}
            settings.write_text(json.dumps(original))
            host.write_text(json.dumps({'id': 'mobile-mac', 'target': 'mobile-mac'}))
            command = [sys.executable, str(Path(__file__).with_name('register-host.py')), str(settings), str(host)]
            subprocess.run(command, check=True)
            before = settings.stat().st_mtime_ns
            subprocess.run(command, check=True)
            current = json.loads(settings.read_text())
            self.assertEqual(current['opaque'], original['opaque'])
            self.assertEqual(current['deviceHosts'][0], original['deviceHosts'][0])
            self.assertEqual(len(current['deviceHosts']), 2)
            self.assertEqual(before, settings.stat().st_mtime_ns)
            self.assertEqual(json.loads((root / 'settings.before-mobile-host.json').read_text()), original)

if __name__ == '__main__': unittest.main()
