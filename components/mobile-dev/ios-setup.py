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
    runtime = max(available, key=lambda r: tuple(map(int, r['version'].split('.'))))
    phones = [d for d in device_types if d.get('productFamily') == 'iPhone']
    if not phones:
        raise RuntimeError('Xcode reports no iPhone device types.')
    parts = [int(part) for part in runtime['version'].split('.')] + [0, 0]
    version_code = (parts[0] << 16) | (parts[1] << 8) | parts[2]
    supported = [d for d in phones if d.get('minRuntimeVersion', 0) <= version_code
                 <= d.get('maxRuntimeVersion', 0x7fffffff)]
    if not supported:
        raise RuntimeError('No iPhone type supports the installed iOS runtime.')
    return runtime['identifier'], supported[-1]['identifier']


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
