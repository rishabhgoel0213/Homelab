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
