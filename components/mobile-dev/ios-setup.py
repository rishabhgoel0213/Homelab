"""Provision Apple-owned Xcode assets outside the Nix store, on explicit deploy."""
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import math


def gate():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://100.73.159.103:1022/state', timeout=3) as response:
            state = json.load(response)
        age = state.get('ageSeconds')
        valid = (state.get('schema') == 1 and state.get('state') == 'unbricked'
                 and state.get('latchedBricked') is False
                 and type(age) in (int, float) and math.isfinite(age) and 0 <= age <= 3)
        if not valid:
            raise RuntimeError('Brick is enabled or its state is stale/unknown.')
    except Exception as error:
        raise RuntimeError(f'Cannot authorize Mac setup: {error}') from error


def run(*args, capture=False, admin=False):
    gate()
    command = ['brick-admin', 'run', *args] if admin else list(args)
    return subprocess.check_output(command, text=True) if capture else subprocess.run(command, check=True)


def choose_device(runtimes, device_types):
    available = [r for r in runtimes if r.get('isAvailable') and '.iOS-' in r['identifier']]
    if not available:
        raise RuntimeError('No available iOS runtime after download; inspect Xcode Settings > Components.')
    phones = [d for d in device_types if d.get('productFamily') == 'iPhone']
    if not phones:
        raise RuntimeError('Xcode reports no iPhone device types.')
    candidates = []
    for runtime in available:
        version = tuple(map(int, runtime['version'].split('.')))
        parts = list(version) + [0, 0]
        version_code = (parts[0] << 16) | (parts[1] << 8) | parts[2]
        # Same-version runtimes can target different hardware. Loose min/max
        # bounds on a device type do not establish runtime compatibility.
        identifiers = None
        if 'supportedDeviceTypes' in runtime:
            identifiers = {d['identifier'] for d in runtime['supportedDeviceTypes']}
        supported = [d for d in phones
                     if (identifiers is None or d['identifier'] in identifiers)
                     and d.get('minRuntimeVersion', 0) <= version_code
                     <= d.get('maxRuntimeVersion', 0xffffffff)]
        if supported:
            candidates.append((version, runtime, supported))
    if not candidates:
        raise RuntimeError('No iPhone type supports the installed iOS runtime.')
    # Prefer the general runtime over a hardware-specific variant at the same
    # version. Within it, choose a recent iPhone rather than the last/oldest entry.
    _, runtime, supported = max(candidates, key=lambda c: (c[0], len(c[2]), c[1]['identifier']))
    phone = max(supported, key=lambda d: d.get('minRuntimeVersion', 0))
    return runtime['identifier'], phone['identifier']


def main():
    if sys.platform != 'darwin' or os.geteuid() == 0:
        raise RuntimeError('Run mobile-ios-setup as the logged-in Mac user, not root.')
    developer = Path('/Applications/Xcode.app/Contents/Developer')
    if not developer.exists():
        print('Installing Xcode from the App Store. Apple may request authentication on the Mac.', flush=True)
        try:
            run(os.environ['MOBILE_MAS'], 'get', '497799835', admin=True)
        except subprocess.CalledProcessError as error:
            raise RuntimeError('Xcode installation needs a signed-in App Store account. Complete any Apple prompt '
                               'on the Mac, then rerun mobile-ios-setup. Darwin configuration is already activated.') from error
    if not developer.exists():
        raise RuntimeError('App Store command finished without /Applications/Xcode.app. Install Xcode there and retry.')
    run('/usr/bin/xcode-select', '--switch', str(developer), admin=True)
    os.environ['DEVELOPER_DIR'] = str(developer)
    run('/usr/bin/xcodebuild', '-license', 'accept', admin=True)
    run('/usr/bin/xcodebuild', '-runFirstLaunch', admin=True)
    run('/usr/bin/xcodebuild', '-downloadPlatform', 'iOS', admin=True)
    data = json.loads(run('/usr/bin/xcrun', 'simctl', 'list', '--json', capture=True))
    runtime, device_type = choose_device(data['runtimes'], data['devicetypes'])
    print(f'Selected compatible simulator pair: {device_type} / {runtime}', flush=True)
    if not any(d['name'] == 'Hackathon iPhone' and d.get('isAvailable')
               for d in data['devices'].get(runtime, [])):
        run('/usr/bin/xcrun', 'simctl', 'create', 'Hackathon iPhone', device_type, runtime)
    run('/usr/bin/xcodebuild', '-version')
    print('Xcode and Hackathon iPhone are ready. Add SSH host mobile-mac in T3 Devices.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
