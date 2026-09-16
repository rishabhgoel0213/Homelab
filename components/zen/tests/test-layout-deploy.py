"""Exercise layout deployment without a Mac, sudo, or network access."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


FAKE = r'''
import hashlib, os, pathlib, shlex, subprocess, sys
tool = pathlib.Path(sys.argv[0]).name
mode = os.environ['TEST_MODE']
with open(os.environ['TEST_LOG'], 'a') as log:
    log.write(tool + ' ' + repr(sys.argv[1:]) + '\n')
if tool == 'nix':
    if mode == 'validation': sys.exit(1)
    if sys.argv[1] == 'eval': print('{}', end='')
elif tool == 'scp':
    if mode == 'upload': sys.exit(1)
elif tool == 'ssh':
    command = sys.argv[-1]
    if command.startswith('/usr/bin/mktemp'):
        print('/tmp/zen-layout.AbCd1234' if mode != 'badpath' else '/etc')
    elif command.startswith('sudo'):
        args = shlex.split(command)
        assert args[:3] == ['sudo', '/bin/sh', '-c']
        subprocess.run(['bash', '-n', '-c', args[3]], check=True)
        assert '/bin/mv -f "$stage/manifest" /etc/zen/managed-sidebar.json' in args[3]
        assert args[3].count('shasum -a 256') == 2
        if mode == 'sudo': sys.exit(1)
    elif command.startswith('/usr/bin/shasum'):
        print(('0' * 64 if mode == 'readback' else hashlib.sha256(b'{}').hexdigest())
              + '  /etc/zen/managed-sidebar.json')
'''


class DeployTests(unittest.TestCase):
    def test_success_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('nix', 'ssh', 'scp'):
                path = root / name
                path.write_text(f'#!{sys.executable}\n' + FAKE)
                path.chmod(0o755)
            for mode in ('success', 'validation', 'badpath', 'upload', 'sudo', 'readback'):
                with self.subTest(mode=mode):
                    log = root / 'calls'
                    log.write_text('')
                    result = subprocess.run(
                        ['bash', os.environ['LAYOUT_DEPLOY_SCRIPT']],
                        env={**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}',
                             'DARWIN_OPS_ROOT': directory, 'TEST_LOG': str(log),
                             'TEST_MODE': mode}, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode == 0, mode == 'success', result.stderr)
                    self.assertEqual('checksum verified' in result.stdout, mode == 'success')
                    calls = log.read_text()
                    if mode in ('validation', 'badpath', 'upload'):
                        self.assertNotIn('sudo /bin/sh', calls)
                    if mode == 'validation':
                        self.assertNotIn('ssh ', calls)
                    if mode == 'badpath':
                        self.assertNotIn('/bin/rm', calls)


if __name__ == '__main__':
    unittest.main()
