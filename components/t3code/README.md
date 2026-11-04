# T3 Code nightly

The server runs the official, unmodified upstream nightly at:

https://t3code.internal.therealrishabh.com

The Nix package downloads the versioned Linux x64 release from
[pingdotgg/t3code](https://github.com/pingdotgg/t3code/releases) and verifies its
pinned SHA256. It does not build or execute the private fork.

## Updates

`just t3code-update` resolves npm's official `t3@nightly` tag, updates the
version and hash in `package.nix`, and builds the host without activating it.
It also resolves and hashes the official Android APK attached to that exact
release. Both pins advance together; a release without exactly one matching APK
is rejected. A failed build restores both old pins. An exact nightly version can be supplied
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

## Official nightly Android download

Open https://updates.internal.therealrishabh.com/ on the phone with Tailscale
enabled, then download and install the APK. The stable download URL is
`/nightly.apk`; `/bootstrap.apk` remains an alias for the old bookmarked URL.
`/release.json` identifies the server nightly, original upstream APK filename,
and pinned hash. Caddy serves the verified APK directly from the Nix store and
rejects connections outside the tailnet. Responses disable caching so a phone
does not reuse yesterday's APK. The old custom `/api/manifest` Expo endpoint is
not restored.

Every successful daily nightly deployment switches the server and this download
to the same upstream release. The file is the official, unmodified APK, not a
locally rebuilt fork. Android still requires confirmation to install new APKs;
this endpoint does not push or silently install them. The official app's own
compatible JavaScript updates come from upstream's Expo service and follow
upstream's mobile update channel independently of the server pin. Native changes
require downloading and installing a new APK. A signature mismatch with an old
custom build may require uninstalling that phone app first; save any local drafts
before uninstalling. Server conversations and project files stay on the server.
