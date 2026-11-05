import importlib.util
import io
import contextlib
import pathlib
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('gate', pathlib.Path(__file__).with_name('gate.py'))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class GateTests(unittest.TestCase):
    def test_atomic_verifier_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'verifier'
            gate.atomic(path, 'old')
            gate.atomic(path, 'new')
            self.assertEqual(path.read_text(), 'new')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(path.with_suffix('.new').exists())

    def test_rotation_denies_before_generating_secret(self):
        for observation in (None, {}, {'state': 'bricked'}):
            with patch.object(gate, 'observation', return_value=observation), patch.object(gate.secrets, 'token_bytes') as random:
                with self.assertRaises(RuntimeError):
                    gate.rotate()
                random.assert_not_called()

    def test_successful_rotation_persists_only_verifier(self):
        sample = bytes(range(8))
        fresh = {'schema':1, 'state':'unbricked', 'latchedBricked':False, 'ageSeconds':0}
        with tempfile.TemporaryDirectory() as directory, patch.object(gate, 'STATE', pathlib.Path(directory)):
            path = pathlib.Path(directory) / 'verifier'
            gate.atomic(path, gate.verifier(bytes(32)))
            with patch.object(gate, 'observation', return_value=fresh), patch.object(gate.secrets, 'token_bytes', return_value=sample) as random, patch('builtins.open', return_value=io.StringIO()), patch.object(gate.getpass, 'getpass', return_value=sample.hex()), contextlib.redirect_stdout(io.StringIO()):
                gate.rotate()
            random.assert_called_once_with(8)
            self.assertEqual(path.read_text().strip(), gate.verifier(sample))
            self.assertNotIn(sample.hex(), path.read_text())
            self.assertEqual(list(pathlib.Path(directory).iterdir()), [path])

    def test_bricking_during_confirmation_preserves_old_verifier(self):
        sample = bytes(range(8))
        fresh = {'schema':1, 'state':'unbricked', 'latchedBricked':False, 'ageSeconds':0}
        with tempfile.TemporaryDirectory() as directory, patch.object(gate, 'STATE', pathlib.Path(directory)):
            path = pathlib.Path(directory) / 'verifier'
            gate.atomic(path, 'old-verifier')
            with patch.object(gate, 'observation', side_effect=[fresh, None]), patch.object(gate.secrets, 'token_bytes', return_value=sample) as random, patch('builtins.open', return_value=io.StringIO()), patch.object(gate.getpass, 'getpass', return_value=sample.hex()):
                with self.assertRaises(RuntimeError):
                    gate.rotate()
            self.assertEqual(path.read_text(), 'old-verifier')

    def test_unbricked_does_not_prompt_for_recovery(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(gate, 'STATE', pathlib.Path(directory)):
            gate.atomic(pathlib.Path(directory) / 'verifier', 'verifier')
            with patch.object(gate, 'observation', return_value={'schema':1, 'state':'unbricked', 'latchedBricked':False, 'ageSeconds':0}), patch.object(gate.getpass, 'getpass') as prompt:
                gate.authorize()
                prompt.assert_not_called()


if __name__ == '__main__': unittest.main()
