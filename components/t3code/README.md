# T3 Code nightly

The server runs the official, unmodified upstream nightly at:

https://t3code.internal.therealrishabh.com

The Nix package downloads the versioned Linux x64 release from
[pingdotgg/t3code](https://github.com/pingdotgg/t3code/releases) and verifies its
pinned SHA256. It does not build or execute the private fork.

## Updates

`just t3code-update` resolves npm's official `t3@nightly` tag, updates the
version and hash in `package.nix`, and builds the host without activating it.
A failed build restores the old pin. An exact nightly version can be supplied
as an argument.

`just t3code-auto-update` also deploys when the installed version differs from
the pin, then checks the service and HTTP endpoint. Failed deployments remain
eligible for retry. The systemd timer runs daily at 06:00 America/New_York with
up to ten minutes of randomized delay. It shares the Codex/Pi deployment lock.
Updates restart T3 Code and can interrupt active T3 turns or terminals.

## State and providers

State remains at `/srv/state/t3code`. `CODEX_HOME=/srv/state/codex` shares the
managed Codex authentication. Provider configuration otherwise uses upstream
defaults and the normal upstream Settings UI.

The custom projectctl adapter, Pi provider, task UI, Jupyter editor integration,
and private Android/Expo update service are removed from the deployment.
Use upstream mobile clients. Add project paths in the standard T3 UI; projectctl
continues independently. The old fork checkout is retained for recovery but is
not a package input. Initial migration backups are under
`/srv/state/t3code-backups`.

The initial fork conversion uses `bin/migrate-private-fork.py` with the service
stopped. First provision the backup parent with
`sudo install -d -m 0700 -o rishabh -g users /srv/state/t3code-backups`.
It backs up the entire state, resets fork settings/keybindings, and
reconciles conflicting migration IDs 36, 41, and 42. Upstream then performs its
own schema migration into `userdata/statev2.sqlite`. This is a one-time step,
not part of the nightly updater. To recover the old fork, stop T3 and restore
the full backup together with the prior NixOS generation.

## Operations

```bash
just t3code-doctor
just t3code-pair
just t3code-status
just t3code-logs
systemctl status t3code-auto-update.timer
journalctl -u t3code-auto-update
```

The server binds to loopback port 3773; Caddy provides the existing private HTTPS
route. Pairing is handled by upstream T3. The route remains tailnet-only.
