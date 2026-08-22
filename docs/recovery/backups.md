# Backup And VPS Recovery Runbook

Backrest owns scheduled backups, retention, monitoring, and restores. Restic is
the backup engine underneath. The off-site Hetzner Storage Box repository is:

```text
sftp:hetzner-storage-box:/home/restic/nixos-pc
```

The alias is defined in `/srv/state/backrest/ssh/config`. The direct endpoint is
`u614006@u614006.your-storagebox.de` on port `23`.

## Recovery guarantees and limits

The backup is intentionally broad enough to reconstruct this host even if a
full restore takes hours. It is not a bootable disk image. A replacement agent
must adapt the hardware, boot, GPU, and Tailscale settings to the replacement
VPS before applying the NixOS configuration.

The daily recovery point objective is up to 24 hours. Matrix creates consistent
PostgreSQL dumps before Backrest captures them. Other live SQLite-backed
services are crash-consistent rather than transactionally frozen; inspect and
repair their databases during recovery if necessary.

## Backrest plans

Both `nixos-pc-home` and `nixos-pc-quarterly` use these source paths:

```text
/backup/etc/nixos
/backup/etc/ssh
/backup/home/rishabh
/backup/srv/ops
/backup/srv/state
/backup/var/lib
```

The container mounts those paths read-only from the corresponding host paths.
`/var/lib` captures otherwise easy-to-miss service identity and state such as
Tailscale, Samba, ACME, Caddy, NetworkManager, and any service that has not yet
been moved under `/srv/state`.

Use these excludes in both plans:

```text
/backup/home/rishabh/.cache
/backup/home/rishabh/.codex/.tmp
/backup/home/rishabh/.codex/cache
/backup/home/rishabh/.codex/log
/backup/home/rishabh/.codex/tmp
/backup/home/rishabh/.codex/app-server-daemon/*.log
/backup/home/rishabh/.local/share/Trash
/backup/srv/state/backrest/cache
/backup/var/lib/docker
/backup/var/lib/systemd/coredump
```

Docker images and writable layers are deliberately excluded. Service data must
live in `/srv/state`, `/home/rishabh`, or another listed source; container images
are recreated by NixOS. Coredumps are diagnostic debris, not recovery state.

Use these backup flags:

```text
--exclude-caches
--one-file-system
--tag=homelab
```

The daily plan runs at `15 2 * * *` and retains 30 daily, 4 weekly, and 12
monthly snapshots. The quarterly plan runs at `15 3 1 */3 *`, adds the
`quarterly` tag, and keeps all of its snapshots. Repository prune and check run
at `0 0 1 * *`; repository-wide forget is disabled.

## Offline recovery credential bundle

The repository password and SSH key must exist outside both this server and the
Restic repository. Create a single age-encrypted bundle with:

```bash
cd /srv/ops
just recovery-kit
```

The output is `/home/rishabh/nixos-pc-vps-recovery-YYYY-MM-DD.tar.age`, mode
`0600`, encrypted to the deployed `rishabh` SSH authorized key. It contains:

- The Restic password, Storage Box SSH key, SSH configuration, and known host.
- The SOPS-encrypted homelab secrets file and its `.sops.yaml` policy.
- The SSH host private key that decrypts SOPS.
- The Backrest configuration, including plan metadata.
- A README with the repository endpoint and decryption command.

Copy the encrypted file to at least two trusted local devices. Test that the
matching admin SSH private key can decrypt it. Never copy out or commit the
decrypted directory. Regenerate and redistribute the bundle after rotating the
Restic key/password, SOPS recipient, SSH host key, or authorized admin key.

## Routine verification

Confirm both the process and the repository rather than relying on the UI alone:

```bash
systemctl is-active docker-backrest.service
curl -fsS http://127.0.0.1:9898/ >/dev/null
sudo docker exec backrest getent ahostsv4 u614006.your-storagebox.de
```

In Backrest, confirm the latest operation succeeded and periodically inspect the
latest snapshot paths. Repository checks currently validate repository metadata;
schedule a non-zero data subset or an occasional full read check when practical.

## Blank-VPS recovery procedure

These steps assume the original host is unavailable. If it might return, do not
run two machines with the same SSH or Tailscale identity at the same time.

### 1. Decrypt the recovery bundle

On a trusted machine with the matching admin SSH private key:

```bash
mkdir -m 0700 /tmp/nixos-pc-recovery
age -d -i /path/to/admin-private-key \
  nixos-pc-vps-recovery-YYYY-MM-DD.tar.age \
  | tar -xvf - -C /tmp/nixos-pc-recovery
```

The paths below are relative to `/tmp/nixos-pc-recovery/recovery`.

### 2. Verify direct Restic access

Use the recovered key without installing Backrest first:

```bash
chmod 0600 restic/restic-ssh-key restic/restic-password
export RESTIC_REPOSITORY='sftp:u614006@u614006.your-storagebox.de:/home/restic/nixos-pc'
export RESTIC_PASSWORD_FILE="$PWD/restic/restic-password"
export RESTIC_SFTP_COMMAND="ssh -i $PWD/restic/restic-ssh-key -p 23 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$PWD/restic/known_hosts"
restic snapshots
```

Do not proceed until the intended latest daily or quarterly snapshot is visible.

### 3. Prepare a VPS-compatible NixOS host

Use an `x86_64-linux` VPS with enough disk for the desired restore tier. Boot a
NixOS installer or provider image and obtain root SSH access. An agent should
then restore `/srv/ops` to a staging location and create a VPS-specific host in
the flake rather than applying `nixos-pc` unchanged:

1. Generate or write hardware configuration for the VPS disk and boot mode.
2. Remove the physical host's disk UUIDs and Intel-specific assumptions.
3. Disable the NVIDIA module and GPU/local-model services unless the VPS has a
   compatible NVIDIA GPU.
4. Keep bulk services disabled initially if the VPS disk is intentionally small.
5. Add the new flake output and run `nix flake check --impure` before switching.

The current physical-host configuration is a source template, not a portable
cloud image.

### 4. Restore files into staging

Restore into a temporary filesystem first:

```bash
mkdir -p /mnt/restore
restic restore latest --target /mnt/restore
```

The snapshot contains a `/backup` prefix. Copy each source back to its real
location, preserving ownership, modes, links, ACLs, and xattrs:

```bash
rsync -aHAX /mnt/restore/backup/srv/ops/ /srv/ops/
rsync -aHAX /mnt/restore/backup/home/rishabh/ /home/rishabh/
rsync -aHAX /mnt/restore/backup/srv/state/ /srv/state/
rsync -aHAX /mnt/restore/backup/etc/nixos/ /etc/nixos/
rsync -aHAX /mnt/restore/backup/etc/ssh/ /etc/ssh/
rsync -aHAX /mnt/restore/backup/var/lib/ /var/lib/
```

Restore `/var/lib` before starting application services. Do not copy the
excluded Docker directory from any unrelated source.

If restoring the old SSH host identity, install its private keys as root mode
`0600`. The Ed25519 host key is also the SOPS age identity. If the original host
may come back, instead generate a new host key and use an offline SOPS recovery
identity to re-encrypt the secrets for the new recipient.

### 5. Validate secrets and apply NixOS

Before enabling services:

```bash
cd /srv/ops
sops --decrypt /home/rishabh/.config/homelab/secrets.yaml >/dev/null
just secrets-check
nix flake check --impure
sudo nixos-rebuild switch --impure --flake .#<vps-host>
```

Do not print decrypted secrets. Confirm ownership of `/srv/state` and
`/home/rishabh` after the first activation.

### 6. Re-establish network identity

Choose whether to restore or replace the old Tailscale node identity. For a new
identity, clear only the restored Tailscale state, enroll the VPS, then update:

- `homelab.tailnetIp` and `homelab.tailnetIpv6`.
- Services that bind directly to the old tailnet address.
- The Tailscale restricted nameserver for `internal.therealrishabh.com`.
- Any internal wildcard DNS record that points to the old tailnet address.

The recovered SOPS file contains the Cloudflare Tunnel and API credentials.
Start the tunnel only after ensuring the unavailable host will not concurrently
serve the same tunnel. Verify both public and private routes after cutover.

### 7. Restore and verify services in dependency order

Bring up and verify approximately in this order:

1. SOPS secrets, networking, Tailscale, DNS, Caddy, and Cloudflare Tunnel.
2. Vaultwarden and its `/srv/state/vaultwarden` database/key material.
3. Matrix PostgreSQL and bridges; use `/srv/state/matrix/backups/*.dump` if the
   raw PostgreSQL directory is not cleanly recoverable.
4. Syncthing, Samba, Canvas, JupyterLab, T3, Codex, Pi, blog, and media services.
5. Bulk downloads, local models, caches, and GPU-dependent services.

For every important service, verify the systemd unit, its loopback endpoint,
the routed endpoint, and application-level data. For SQLite services, run the
application's integrity check before accepting the recovery.

### 8. Finish and fail back safely

Keep the original host powered down or isolated while the VPS uses restored
machine identities. Record DNS/Tailscale changes. When failing back, stop the
VPS services first, take a final backup, restore newer mutable state to the
physical host, reverse DNS, and only then reconnect the original host.

Delete the decrypted recovery directory securely when recovery is complete;
retain the encrypted bundle on trusted devices.
