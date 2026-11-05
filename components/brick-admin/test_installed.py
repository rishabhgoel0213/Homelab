# Run as root under: unshare --mount --net --fork python3 test_installed.py
# Uses a test-only verifier in a private mount namespace; never enrolls a host.
import hashlib, os, pathlib, pty, select, tempfile, subprocess, shutil, time
assert os.geteuid() == 0, 'Run under sudo unshare, not as an ordinary user'
for namespace in ('mnt', 'net'):
    assert os.readlink('/proc/self/ns/' + namespace) != os.readlink('/proc/1/ns/' + namespace), 'Refusing to test in a host namespace'
state = pathlib.Path(tempfile.mkdtemp(prefix='brick-guard-test-'))
try:
    # Deliberately fixed test material; never enrolled on either live host.
    secret = bytes(32).hex()
    (state / 'verifier').write_text(hashlib.sha256(b'homelab-brick-admin-v1\0' + bytes(32)).hexdigest())
    os.chmod(state / 'verifier', 0o600)
    subprocess.run(['mount', '--make-rprivate', '/'], check=True)
    subprocess.run(['mount', '--bind', str(state), '/var/lib/brick-admin'], check=True)
    def run(args, answer=None):
        pid, fd = pty.fork()
        if pid == 0:
            helper = os.environ.get('BRICK_TEST_HELPER', '/etc/brick-admin-root')
            os.execv(helper, [helper] + args)
        output = b''
        answered = False
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if ready:
                try: chunk = os.read(fd, 4096)
                except OSError: break
                if not chunk: break
                output += chunk
                if b'Recovery secret:' in output and answer is not None and not answered:
                    os.write(fd, answer.encode() + b'\n')
                    answered = True
        else:
            os.kill(pid, 9)
            raise AssertionError('Timed out')
        os.close(fd)
        _, status = os.waitpid(pid, 0)
        assert secret.encode() not in output, 'Secret echoed'
        return os.waitstatus_to_exitcode(status), output
    status, output = run(['run', '/run/current-system/sw/bin/id'], secret)
    assert status == 0 and b'uid=0(root)' in output, output.replace(secret.encode(), b'[redacted]')
    status, output = run(['run', '/run/current-system/sw/bin/id'], '1' * 64)
    assert status != 0 and b'uid=0(root)' not in output
    status, output = run(['rotate'])
    assert status != 0 and b'Rotation requires' in output
    print('PASS: packaged helper requires valid recovery during outage; wrong key and rotation denied; secret not echoed')
finally:
    subprocess.run(['umount', '/var/lib/brick-admin'], check=False)
    shutil.rmtree(state)
