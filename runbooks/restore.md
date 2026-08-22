# Restore Runbook

For total-host loss or migration to a blank VPS, use the complete procedure in
[`backups.md`](backups.md#blank-vps-recovery-procedure). That procedure covers
the offline credential bundle, direct Restic access without Backrest, staged
path restoration, VPS-specific NixOS changes, network cutover, service ordering,
verification, and safe failback.

## Backrest UI

Backrest owns this repository. Prefer browsing snapshots and restoring files
from:

```text
https://backups.internal.therealrishabh.com
```

## Restore A Service State Directory

Use Backrest to restore into a temporary directory first, inspect the restored
files, then stop the affected service and replace its live state directory.

```bash
sudo systemctl stop vaultwarden.service
```

Do not overwrite live state without inspecting the restored files first.
