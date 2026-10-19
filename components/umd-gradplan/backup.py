"""Consistent SQLite snapshots; retain the latest 30 daily backups."""
import os,sqlite3,sys
from datetime import datetime,timezone
from pathlib import Path
os.umask(0o077)
state=Path(sys.argv[1]);source=state/'workspace.sqlite'
if source.exists():
    backups=state/'backups';backups.mkdir(mode=0o700,exist_ok=True)
    target=backups/(datetime.now(timezone.utc).strftime('%Y-%m-%d')+'.sqlite')
    temp=target.with_suffix('.tmp')
    with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as src,sqlite3.connect(temp) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup integrity check failed')
    temp.replace(target)
    for old in sorted(backups.glob('*.sqlite'),reverse=True)[30:]:old.unlink()
    print('Consistent graduation-planner snapshot saved')
