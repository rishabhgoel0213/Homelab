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

`just t3code-auto-update` runs in `/home/rishabh/Projects/Homelab`, commits both
pins, pushes origin/main, fast-forwards `/srv/ops`, and deploys that same commit
through the shared `tools/deploy` workflow. It checks the service and matching
APK endpoint. Updates defer during uncommitted work; failed publications and
deployments remain eligible for retry. The systemd timer runs daily at 06:00 America/New_York with
up to ten minutes of randomized delay. It shares the Codex/Pi deployment lock.
Updates restart T3 Code and can interrupt active T3 turns or terminals.

## State and providers

State remains at `/srv/state/t3code`. `CODEX_HOME=/srv/state/codex` shares the
managed Codex authentication. Provider configuration otherwise uses upstream
defaults and the normal upstream Settings UI.

The custom projectctl adapter, Pi provider, task UI, Jupyter editor integration,
and private Android/Expo update service are removed from the deployment.
Use upstream mobile clients. Add project paths in the standard T3 UI or import
an existing project from the server shell:

```bash
t3-project-import rdx-run2-analysis-v2
```

The command accepts a `projectctl` name, ID, or path and passes the resolved
title and workspace root to upstream `t3 project add`. It registers one
project per invocation. T3 reports an error if the workspace is already
registered.

The old fork checkout is retained for recovery but is not a package input.
Initial migration backups are under
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

Deployments preserve the running T3 Code service and its active sessions.
As with Codex remote control, `restartIfChanged = false` defers package and
service changes until a manual `brick-admin run systemctl restart t3code.service` or a
reboot. Restart manually when sessions can safely be interrupted. Automatic
recovery after a process failure remains enabled.

## Linux web dependencies

The service provides nix-ld libraries for upstream's version-matched downloaded
Chrome headless shell, keeping its sandbox enabled. PDF preview is supplied by
upstream's client; Poppler utilities and FFmpeg are also available.
After deployment, finish active turns and run
`brick-admin run systemctl restart t3code.service` to pick up the new service
environment (with the phone unbricked).

## MacBook backend server and multidevice linking

`components/t3code/darwin.nix` (imported by `profiles/darwin/workstation.nix` and enabled via
`homelab.t3code.enable = true` in `hosts/macbook/default.nix`) deploys the official `darwin-arm64`
T3 Code server and CLI on the MacBook so T3 Code's multidevice and linked-environment features
work directly without relying on SSH.

- **Packaging and signed updates:** `package.nix` builds `.#macbook-t3code` on `nixos-pc` with
  `dontFixup = true` to preserve upstream's macOS code signature and pins the store path in
  `components/darwin-deploy/artifacts.nix`. `just t3code-update` advances the Linux, Mac, and
  Android APK pins together. `just t3code-auto-update` (and `just t3code-publish-mac`) signs and
  publishes the Mac package to `/srv/state/t3code-mac-release/current.json`. On the MacBook, the
  `com.therealrishabh.t3code-update` LaunchAgent checks every 30 minutes, verifies the Nix
  signature and `codesign --verify --strict`, and atomically updates its user profile without
  interrupting active sessions. Run `t3code-restart` on the MacBook when ready to restart the
  server onto a newly downloaded nightly.
- **Runtime service and state:** The `com.therealrishabh.t3code` LaunchAgent runs `t3code-server`,
  which binds strictly to loopback (`127.0.0.1:3773`) with `T3CODE_HOME=~/.local/state/t3code`
  (keeping the backend isolated from any stale `~/.t3` state and free of spaces in worktree paths).
  Package profiles and logs live under `~/Library/Application Support/Homelab/t3code`.
- **Tailscale Serve HTTPS:** By default `t3code-server` passes `--tailscale-serve` on HTTPS port
  443, publishing the loopback backend exclusively on the tailnet at
  `https://macbook.tail2f4d27.ts.net` (leaving the existing HTTP port 80 Serve route untouched).
- **Activation and pairing:**
  1. Deploy the MacBook configuration explicitly with `MACBOOK_DEPLOY_CONFIRM=deploy just darwin-deploy`.
  2. On the MacBook, verify the server and mint a pairing code:
     ```bash
     t3 status
     t3 pair --tailscale
     ```
  3. Add `https://macbook.tail2f4d27.ts.net` directly from the T3 mobile/web UI, or link the two
     servers so agents on `nixos-pc` can delegate directly to the MacBook environment:
     ```bash
     t3 environment link --base-dir /srv/state/t3code https://macbook.tail2f4d27.ts.net
     ```

## Zen Browser session cookie sync

T3 Code's server-side browser on `nixos-pc` uses `chrome-headless-shell`, which Google and some
other SSO providers reject during interactive login. To keep T3's in-app browser signed into your
existing sessions without exposing saved passwords to `nixos-pc`:

- **Cookies only, never passwords:** `t3-browser-sync` on the MacBook reads only a private temporary
  copy of Zen's `cookies.sqlite` (+ WAL/SHM sidecars), never touching `logins.json`, `key4.db`,
  history, or macOS Keychain. Internal/tailnet hosts (`localhost`, `*.internal.therealrishabh.com`,
  `*.ts.net`, `*.local`), expired cookies, private-browsing cookies, and partitioned third-party
  cookies are skipped automatically. Add extra domain suffixes to exclude (one per line) in
  `~/Library/Application Support/Homelab/t3-browser-sync/exclude-domains.txt`.
- **Continuous background sync:** The `com.therealrishabh.t3code-browser-sync` LaunchAgent runs
  `t3-browser-sync --background` at login and every 30 minutes. It hashes the active cookie set
  locally (skipping SSH entirely when nothing changed) and streams updates over SSH stdin to
  `t3-browser-cookie-receive` on `nixos-pc`, which applies them via T3's bundled `playwright-core`
  only when `chrome-headless-shell` is stopped or idle for at least 10 minutes.
- **One-time backup / immediate sync (run on MacBook):**
  ```bash
  t3-browser-sync                     # sync all active Zen logins now (refreshes T3's browser process)
  t3-browser-sync --domain google.com # sync only Google cookies now
  t3-browser-sync --dry-run           # preview cookie/domain counts without touching nixos-pc
  t3-browser-sync --status            # show detected Zen profile and last sync summary
  ```
  Refreshing T3's browser stops only the `chrome-headless-shell` child process — `t3code.service`,
  active chats, agents, and terminals stay running, and the next tab open loads the fresh cookies.


