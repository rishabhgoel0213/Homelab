# SMB Runbook

Samba exposes a private Finder-mountable SMB share for server-only files.

Open from macOS Finder with:

```text
smb://files.internal.therealrishabh.com/Remote
```

Use:

```text
Username: rishabh
Password: value of samba-password from sops
```

The share path on the server is:

```text
/home/rishabh/Remote
```

`files.internal.therealrishabh.com` resolves through the internal CoreDNS
wildcard to the server's Tailscale IP. Samba binds to localhost and
`tailscale0` only, with guest access disabled.

To retrieve the password on the server:

```bash
cd /srv/ops
sudo env SOPS_AGE_KEY_CMD='/run/current-system/sw/bin/ssh-to-age -private-key -i /etc/ssh/ssh_host_ed25519_key' \
  sops --config /srv/ops/.sops.yaml --decrypt --extract '["samba-password"]' \
  /home/rishabh/.config/homelab/secrets.yaml
```

To make the mount persistent on macOS:

1. Connect once in Finder with `Cmd-K`.
2. Save the password in Keychain.
3. Add the mounted volume to Login Items.

For a fixed path, use macOS `autofs` after verifying the Finder mount works.

## Android downloads

Open <https://smb.internal.therealrishabh.com> while connected to Tailscale.
Install the pinned upstream CIFS Documents Provider APK and import `homelab.cifs`
from Settings → Import settings using the public import password `homelab` and
Append. Edit the imported connections to enter the existing Samba password.
Neither artifact contains credentials. Android installation and import require
user interaction; the APK itself is unmodified and retains upstream signing.

The profile uses the server's Tailscale IP, SMBJ with encryption, and the
`rishabh` account. Downloads exposes `/home/rishabh/Downloads` read-only with
symlink traversal disabled. Remote retains its existing read/write behavior.
The download route rejects requests outside Tailscale's address ranges.

`mobile-profile.py` implements the 2.4.0 release's `ConnectionIO`, `EncryptUtils`,
`DomainMapper`, and `StorageConnection.Cifs` serialization. Its embedded upstream
format key and the import password are public constants, not account secrets.
When upgrading the APK, verify that format against the corresponding source tag
and update the fixed-output hash in `mobile.nix`.
