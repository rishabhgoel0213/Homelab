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
    def inventory(self, devices):
        return {'runtimes': [], 'devicetypes': [], 'devices': {'com.apple.CoreSimulator.SimRuntime.iOS-27-2': devices}}

    def test_consolidation_preserves_current_device_and_removes_other_simulators(self):
        devices = [{'udid': 'keep', 'name': 'Hackathon iPhone', 'isAvailable': True, 'state': 'Booted'},
                   {'udid': 'extra', 'name': 'iPhone Pro Max', 'isAvailable': True, 'state': 'Shutdown'}]
        with patch.object(setup, 'choose_device', return_value=('com.apple.CoreSimulator.SimRuntime.iOS-27-2', 'phone')), patch.object(setup, 'run') as run:
            setup.configure_devices(self.inventory(devices))
            self.assertEqual(run.call_args_list, [unittest.mock.call('/usr/bin/xcrun', 'simctl', 'rename', 'keep', 'iPhone'),
                                                  unittest.mock.call('/usr/bin/xcrun', 'simctl', 'delete', 'extra')])

    def test_consolidation_is_idempotent(self):
        devices = [{'udid': 'keep', 'name': 'iPhone', 'isAvailable': True, 'state': 'Booted'}]
        with patch.object(setup, 'choose_device', return_value=('com.apple.CoreSimulator.SimRuntime.iOS-27-2', 'phone')), patch.object(setup, 'run') as run:
            setup.configure_devices(self.inventory(devices))
            run.assert_not_called()

    def test_consolidation_refuses_another_running_device_before_changes(self):
        devices = [{'udid': 'other', 'name': 'iPhone Pro Max', 'isAvailable': True, 'state': 'Booted'}]
        with patch.object(setup, 'choose_device', return_value=('com.apple.CoreSimulator.SimRuntime.iOS-27-2', 'phone')), patch.object(setup, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Close other running'):
                setup.configure_devices(self.inventory(devices))
            run.assert_not_called()

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

    def test_same_version_hardware_runtime_does_not_win_over_general_runtime(self):
        phones = [
            {'identifier': 'iphone-18-pro', 'productFamily': 'iPhone', 'minRuntimeVersion': 27 << 16},
            {'identifier': 'iphone-duo', 'productFamily': 'iPhone', 'minRuntimeVersion': 27 << 16},
            {'identifier': 'iphone-11', 'productFamily': 'iPhone', 'minRuntimeVersion': 13 << 16},
        ]
        specialized = {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-27-2-iPhone19-4',
                       'version': '27.2', 'isAvailable': True,
                       'supportedDeviceTypes': [{'identifier': 'iphone-duo'}]}
        general = {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-27-2',
                   'version': '27.2', 'isAvailable': True,
                   'supportedDeviceTypes': [{'identifier': 'iphone-18-pro'}, {'identifier': 'iphone-duo'}]}
        for runtimes in ([specialized, general], [general, specialized]):
            self.assertEqual(setup.choose_device(runtimes, phones), (general['identifier'], 'iphone-18-pro'))
        self.assertEqual(setup.choose_device([specialized], phones), (specialized['identifier'], 'iphone-duo'))

    def test_explicit_empty_supported_list_is_not_treated_as_unrestricted(self):
        runtime = {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-27-2', 'version': '27.2',
                   'isAvailable': True, 'supportedDeviceTypes': []}
        with self.assertRaisesRegex(RuntimeError, 'No iPhone type supports'):
            setup.choose_device([runtime], [{'identifier': 'phone', 'productFamily': 'iPhone'}])

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
