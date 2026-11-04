"""One-time, offline conversion from the retired private fork to upstream.

Run with python3 as rishabh after stopping t3code.service. The complete old
state is backed up before changing migration metadata or resetting settings.
The official binary performs all subsequent schema and conversation migration.
"""
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
import subprocess


state = Path('/srv/state/t3code')
database = state / 'userdata/state.sqlite'
if subprocess.run(['systemctl', 'is-active', '--quiet', 't3code.service']).returncode == 0:
    raise SystemExit('Stop t3code.service before running this offline conversion.')
if (state / 'userdata/statev2.sqlite').exists():
    raise SystemExit('Upstream statev2.sqlite already exists; refusing to repeat conversion.')
with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
    history = dict(db.execute('SELECT migration_id, name FROM effect_sql_migrations'))
    if history.get(41) != 'ProjectionProjectKind' or history.get(42) != 'RepairProjectionThreadsPinned' or max(history) != 42:
        raise SystemExit('Unexpected migration history; refusing to modify state.')
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise SystemExit('Database integrity check failed.')

backup_root = Path('/srv/state/t3code-backups')
backup_root.mkdir(mode=0o700, exist_ok=True)
backup = backup_root / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-private-fork')
shutil.copytree(state, backup, symlinks=True)
backup.chmod(0o700)
with sqlite3.connect(database) as db:
    # IDs 41 and 42 in the fork masked upstream's auth connection and linked-PR
    # migrations. Let upstream execute its own versions on the next startup.
    db.execute('DELETE FROM effect_sql_migrations WHERE migration_id IN (41, 42)')
    # Fork migration 36 was a project-kind customization. Its later repair at
    # 42 already applied upstream 36's pinned_at column; record the true schema.
    db.execute("UPDATE effect_sql_migrations SET name='ProjectionThreadsPinned' WHERE migration_id=36")
    db.commit()
for name in ('settings.json', 'keybindings.json'):
    (state / 'userdata' / name).unlink(missing_ok=True)
print(f'Full recovery backup: {backup}')
print('Reconciled migration history and reset fork settings/keybindings. Conversations retained.')
