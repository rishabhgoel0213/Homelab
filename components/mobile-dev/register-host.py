"""Merge only the managed SSH device host into T3's watched settings file."""
import json
import os
from pathlib import Path
import sys
import tempfile

settings = Path(sys.argv[1])
host = json.loads(Path(sys.argv[2]).read_text())
data = json.loads(settings.read_text()) if settings.exists() else {}
hosts = data.get('deviceHosts', [])
if not isinstance(hosts, list):
    sys.exit('Refusing to replace malformed T3 deviceHosts setting.')
existing = next((h for h in hosts if h.get('id') == host['id']), None)
if existing != host:
    if settings.exists():
        backup = settings.with_name('settings.before-mobile-host.json')
        if not backup.exists():
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(settings.read_text())
    data['deviceHosts'] = [h for h in hosts if h.get('id') != host['id']] + [host]
    settings.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=settings.parent, prefix='.mobile-settings-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, settings)
    finally:
        if os.path.exists(name):
            os.unlink(name)
