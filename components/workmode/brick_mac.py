"""Keep a strict, untimed Workmode session aligned with the tailnet Brick relay."""
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import time
import urllib.request
import workmode as w

URL = 'http://100.73.159.103:8127/state'
PREFIX = 'Workmode/brick-study/'


def fetch():
    request = urllib.request.Request(URL, headers={'Cache-Control': 'no-cache'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=4) as response:
        raw = response.read(16385)
        if len(raw) > 16384:
            raise w.Error('Oversized Brick bridge response')
        return validate(json.loads(raw))


def validate(data):
    if (data.get('schema') != 1 or data.get('state') not in ('bricked', 'unbricked', 'unknown')
            or type(data.get('latchedBricked')) is not bool):
        raise w.Error('Invalid Brick bridge response')
    age = data.get('ageSeconds')
    if data['state'] != 'unknown' and (type(age) not in (int, float) or not 0 <= age <= 10):
        raise w.Error('Stale Brick bridge response')
    if data['state'] == 'unbricked' and data['latchedBricked']:
        raise w.Error('Inconsistent Brick bridge response')
    return data


def control(request):
    directory = Path(f'/tmp/abstand-{os.getuid()}')
    st = directory.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise w.Error('Unsafe Abstand control directory')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(8)
        connection.connect(str(directory / 'com.buildergroup.abstand.sock'))
        connection.sendall(json.dumps(request).encode() + b'\n')
        with connection.makefile('rb') as f:
            raw = f.readline(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024 or not raw.endswith(b'\n'):
        raise w.Error('Invalid Abstand response')
    reply = json.loads(raw)
    if reply.get('status') != 'ok':
        raise w.Error(reply.get('message', 'Abstand rejected Brick request'))
    return reply['result']


def name_for(profile):
    return PREFIX + hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()[:16]


def matches(item, p):
    b = item['behavior']
    return (b['type'] == 'block' and b['scope'] == 'blockTargets'
        and b['enforcementMode'] == 'strict' and item['pausedAt'] is None
        and sorted((t['action'], t['app']['bundleId']) for t in b['appTargets']) == sorted(('block', a) for a in set(p['blocked_apps']))
        and sorted((t['action'], t['website']['hostname'], t.get('path')) for t in b['websiteTargets']) == sorted(('block', s, None) for s in set(p['blocked_sites']))
        and len(item['conditions']) == 2
        and {c['transition'] for c in item['conditions']} == {'start', 'end'}
        and all(c['rule'] == {'type': 'manual'} for c in item['conditions']))


class Backend(w.Abstand):
    def brick_ready(self):
        self.ready()
        if self.call('status').get('brickControl') is not True:
            raise w.Error('Brick-enabled Abstand build is not running; deploy and restart it')
        self.check_recovery()

    def prepare_brick(self, p):
        if not p['blocked_apps'] and not p['blocked_sites']:
            raise w.Error('Study has no blocklist')
        name = name_for(p)
        found = [i for i in self.intentions() if i['name'] == name and matches(i, p)]
        if found:
            return found[0]['id']
        # Inactive saved intentions may be edited/paused in the UI. Preserve
        # those records and create a valid replacement instead of losing sync.
        targets = [{'type': 'website', 'action': 'block', 'hostname': s} for s in sorted(set(p['blocked_sites']))]
        targets += [{'type': 'app', 'action': 'block', 'stableId': a, 'bundleId': a} for a in sorted(set(p['blocked_apps']))]
        item = control({'command': 'createIntention', 'params': {'name': name,
            'behavior': {'type': 'block', 'enforcementMode': 'strict', 'balancedDelayMs': 15000,
                         'scope': 'blockTargets', 'targets': targets},
            'conditions': [{'transition': t, 'rule': {'type': 'manual'}} for t in ('start', 'end')]}})
        if not matches(item, p):
            raise w.Error('Backend did not preserve the Brick restrictions')
        return item['id']

    def release_brick(self, intention_id):
        # The backend independently fetches the relay; this request cannot force an unlock.
        control({'command': 'releaseBrick', 'intentionId': intention_id})
        if any(s['id'] == intention_id for s in self.sessions()):
            raise w.Error('Brick session remains active')


def reconcile(profile, backend, observation, latched):
    sessions = [s for s in backend.sessions() if s['name'].startswith(PREFIX)]
    if observation['state'] == 'unbricked':
        for session in sessions:
            backend.release_brick(session['id'])
        return False
    desired = latched or observation['latchedBricked'] or observation['state'] == 'bricked' or bool(sessions)
    if desired and not sessions:
        backend.start(backend.prepare_brick(profile))
    return desired


def save_status(directory, result):
    temp = directory / 'brick.json.tmp'
    with temp.open('w') as handle:
        json.dump(result, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, directory / 'brick.json')


def main():
    config = w.load_config('/etc/workmode/profiles.json')
    backend = Backend()
    while True:
        try:
            observation = fetch()
        except Exception:
            observation = {'state': 'unknown', 'latchedBricked': False}
        try:
            with w.mutex() as directory:
                path = directory / 'brick.json'
                previous = json.loads(path.read_text()) if path.exists() else {}
                latched = previous.get('latchedBricked', False)
                # Persist a received lock before backend operations, including failure paths.
                if observation['state'] == 'bricked' or observation['latchedBricked']:
                    latched = True
                result = {'state': observation['state'], 'latchedBricked': latched,
                          'updatedAt': time.time(), 'error': None}
                if latched and not previous.get('latchedBricked', False):
                    save_status(directory, result)
                try:
                    backend.brick_ready()
                    result['latchedBricked'] = reconcile(config['profiles']['study'], backend, observation, latched)
                except Exception as exc:
                    result['error'] = str(exc)[:300]
                save_status(directory, result)
        except Exception as exc:
            print(f'Brick controller: {type(exc).__name__}', flush=True)
        time.sleep(5)


if __name__ == '__main__':
    main()
