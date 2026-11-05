"""Root-only administrative broker. Configuration is substituted by Nix."""
import fcntl
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import resource
import secrets
import subprocess
import sys
import urllib.request

sys.path.insert(0, '@source@')
from policy import accepts, fresh_unbricked, verifier

STATE = Path('@state@')
USER = '@user@'
HELPER = '@helper@'
URL = 'http://100.73.159.103:1022/state'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise OSError('Redirect refused')


def observation():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(URL, timeout=2) as response:
            data = response.read(16385)
        return json.loads(data) if len(data) <= 16384 else None
    except Exception:
        return None


def atomic(path, value, mode=0o600):
    temp = path.with_suffix('.new')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'w') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temp, mode)
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def stored():
    return (STATE / 'verifier').read_text().strip()


def authorize():
    if not (STATE / 'verifier').exists():
        return  # Explicitly unenrolled; existing privileges remain unchanged.
    if fresh_unbricked(observation()):
        return
    # Unenrolled installations retain the previous administrative policy. This
    # broker itself still fails closed so that its behavior can be tested first.
    try:
        expected = stored()
    except FileNotFoundError:
        raise RuntimeError('Unbrick the phone before using or enrolling this broker')
    with open('/dev/tty', 'w') as terminal:
        secret = getpass.getpass('Brick locked/unknown. Recovery secret: ', stream=terminal)
    if not accepts(secret.strip(), stored()):
        raise RuntimeError('Recovery secret rejected')
    del secret


def rotate(enroll=False):
    if not fresh_unbricked(observation()):
        raise RuntimeError('Rotation requires a fresh unbricked phone; recovery cannot override this')
    if enroll and (STATE / 'verifier').exists():
        raise RuntimeError('Already enrolled; use rotate. Use an authorized root command to repair incomplete enrollment.')
    if not enroll and not (STATE / 'verifier').exists():
        raise RuntimeError('Run enroll first')
    candidate = None
    if enroll:
        directory = STATE / 'sudoers.d'
        directory.mkdir(mode=0o700, exist_ok=True)
        candidate = directory / 'policy.candidate'
        tag = 'PASSWD' if sys.platform == 'darwin' else 'NOPASSWD'
        rules = f'{USER} ALL=(ALL:ALL) !ALL\n{USER} ALL=(root) {tag}: NOSETENV: NOLOG_INPUT: NOLOG_OUTPUT: {HELPER}\n'
        atomic(candidate, rules, 0o440)
        subprocess.run(['@visudo@', '-cf', str(candidate)], check=True, stdout=subprocess.DEVNULL)
    # Never emit the secret on stdout/stderr, into arguments, or into a file.
    value = bytearray(secrets.token_bytes(32))
    encoded = value.hex()
    digest = verifier(value)
    with open('/dev/tty', 'w') as terminal:
        terminal.write('Write down this device recovery secret. It will not be displayed again:\n')
        terminal.write(encoded + '\n')
        terminal.flush()
        confirmed = getpass.getpass('Retype the secret to confirm your paper copy: ', stream=terminal)
    okay = hmac.compare_digest(encoded, confirmed.strip())
    for i in range(len(value)):
        value[i] = 0
    del encoded, confirmed, value
    if not okay:
        raise RuntimeError('Confirmation failed; old secret remains valid')
    if not fresh_unbricked(observation()):
        raise RuntimeError('Phone no longer confirmed unbricked; old secret remains valid')
    atomic(STATE / 'verifier', digest + '\n')
    if enroll:
        os.replace(candidate, directory / 'policy')
        if sys.platform != 'darwin':
            if Path('/run/docker.sock').exists():
                os.chown('/run/docker.sock', 0, 0)
                os.chmod('/run/docker.sock', 0o600)
        atomic(Path('/etc/brick-admin.enrolled'), 'enrolled\n', 0o644)
        if sys.platform == 'darwin':
            subprocess.run(['/usr/sbin/dseditgroup', '-o', 'edit', '-d', USER, '-t', 'user', 'admin'], check=True)
    print('Recovery verifier updated. Store the paper copy securely; previous secrets are invalid.')


def main():
    if sys.argv[1:] == ['probe']:
        sys.exit(0 if fresh_unbricked(observation()) else 1)
    if os.geteuid() != 0:
        raise RuntimeError('Use brick-admin, not the internal helper')
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE, 0o700)
    args = sys.argv[1:]
    if not args:
        raise RuntimeError('Usage: brick-admin status | enroll | rotate | run COMMAND [ARGS...]')
    if args == ['status']:
        print(json.dumps({'enrolled': (STATE / 'verifier').exists(),
                          'policyInstalled': (STATE / 'sudoers.d' / 'policy').exists(),
                          'phoneAllowsAdmin': fresh_unbricked(observation())}))
        return
    if args in (['enroll'], ['rotate']):
        with (STATE / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            rotate(enroll=args == ['enroll'])
        return
    if args[0] != 'run' or len(args) < 2:
        raise RuntimeError('Expected run COMMAND [ARGS...]')
    authorize()
    # No user-controlled Python startup, loader, shell init, or root HOME.
    env = {'PATH': '@path@', 'HOME': '/var/root' if sys.platform == 'darwin' else '/root',
           'USER': 'root', 'LOGNAME': 'root', 'LANG': 'en_US.UTF-8'}
    # Native sudo supplies these fields; Nix/libgit2 uses SUDO_UID to
    # recognize the invoking user's checkout during a root build.
    for key in ('SUDO_UID', 'SUDO_GID', 'SUDO_USER'):
        if key in os.environ:
            env[key] = os.environ[key]
    if os.environ.get('TERM'):
        env['TERM'] = os.environ['TERM']
    os.setgid(0)
    os.setuid(0)
    os.execvpe(args[1], args[1:], env)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('brick-admin: ' + str(error), file=sys.stderr)
        sys.exit(1)
