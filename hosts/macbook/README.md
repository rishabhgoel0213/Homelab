# MacBook nix-darwin migration

The MacBook profile is active. Run future deployments from a terminal other
than Tabby so replacing Tabby cannot interrupt the deployment session.

## Managed boundary

`/Applications/Nix Apps` contains interactive apps and the Workmode Study
launcher. Background utilities (Abstand and SwiftBar) are installed separately
in `/Applications/Nix Background Apps`, declared through
`homelab.backgroundApps.packages`. Both folders are managed by activation;
keep manually installed apps outside them. Finish active Study sessions before
deploying the initial folder migration, then check Abstand permissions and run
`workmode setup` and `workmode doctor`.

The MacBook profile installs the pinned upstream Zen Browser bundle, Firefox
DevTools MCP for optional live-session debugging, Firefox CLI 0.3.0, and its
matching signed Firefox extension.
Zen's tabs, Spaces, history, cookies, and logins are ordinary browser state.
No Space, folder, pin, or route is declared by Nix. The Nix profile also
installs the pinned Tabby archive and the VSCodium presets described below.

The Zen extension policy continues to force-install Bitwarden. Firefox CLI's
matching signed extension is in the Nix store; `zen-firefox-cli-xpi` prints its
exact path. It is installed and paired in the Nix-managed Zen profile. The
native messaging host is registered for the Mac user during nix-darwin
activation. Keeping Firefox CLI out of the system-wide browser policy leaves
extension installation scoped to that profile.

## Browser control from server Codex

All browser tooling runs on the Mac. Codex reaches it through the existing
Tailscale SSH connection; no browser debugging port is exposed on the tailnet.

- `zen-firefox-cli` controls the paired, already-running Nix-managed Zen
  browser. It can list tabs, take page snapshots, click, type, navigate, capture
  screenshots, and inspect supported page state. Run `zen-firefox-cli doctor`
  after activation and approve the pairing in Zen.
- `zen-live` is Mozilla Firefox DevTools MCP attached to the running browser.
  It adds WebDriver BiDi, console, network, and debugger tools. Quit the
  Nix-managed Zen instance and start it with `zen-automation` when these tools
  are needed. Both Marionette and the remote debugging agent remain bound to
  Mac loopback. Restart Zen normally afterward; Marionette changes browser
  fingerprinting while enabled.
The live-session tools can access signed-in pages. Use them for the sites and
actions the user requests. A new Codex session is needed after changing MCP
configuration because its tool catalog is loaded at startup.

- Tabby's current third-party plugins are pinned in
  `components/tabby/plugins/package.json`. Add or update plugins there, regenerate the
  lockfile, and update the Nix dependency hash.
- Nix installs the server-cross-compiled Codex CLI from
  `components/codex/cross-package.nix`. Codex.app itself remains unmanaged.
  Both intentionally share `~/.codex/config.toml` and auth state. The managed
  Mac config trusts `/Users/rishabhgoel` and uses the automatic approval
  reviewer for on-request approvals.
- Tailscale is outside the Darwin configuration. The existing standalone app,
  service, node identity, and local state remain unmanaged and untouched. The
  deployment scripts may use its existing network path only as transport.

## Encrypted recovery set

The 2026-09-22 Zen cutover has a separate, quiescent recovery archive at
`/var/lib/homelab-migration-backups/macbook/20260922T213913Z-zen-cutover/daily-zen-full.tar.gz.age`.
It contains the former `/Applications/Zen.app`, the complete pre-cutover Zen
profile registry and profiles (including the daily-driver profile), the
daily-driver cache, and Zen's shared preferences. The browser was closed while
the archive was streamed from the Mac. It was test-decrypted and fully listed
without writing plaintext to disk; its SHA-256 is
`cb717ef50140609b6dd790eed72daff4a818bd0c78828c0c49b025041fe45588`.
The previous Dock plist is separately encrypted in the same directory as
`dock-before-cleanup.tar.gz.age` (SHA-256
`ea665726c20638d30a816c44c5b92d0c0f5c2540b9ba8c577624e5b1ac9fcae8`).
To recover, first close Zen, then decrypt on the server using the converted
server SSH age identity described below and inspect the archive before
restoring only the required Mac paths. Do not restore the entire shared Zen
profile registry over an active Nix profile without reconciling it.

The pre-cutover daily profile `f6ljpewx.Default (release)` was copied to the
Nix-managed profile `cyy01bkj.Default (release)-1` after both apps were closed.
The copy was byte-compared, its main SQLite databases passed integrity checks,
and the Nix Zen 1.22.2b app launched against it. The user visually confirmed
Spaces, tabs, and sign-ins. The old app, daily profile/cache, and pre-migration
blank Nix profile were subsequently removed from the Mac; the Dock tile now
points to `/Applications/Nix Apps/Zen.app`.

The server-only recovery set is:

`/var/lib/homelab-migration-backups/macbook/20260822T053411Z-macbook`

It contains encrypted Zen, Tabby, SSH, Tailscale user state, and protected
`/Library/Tailscale` machine state. The archives were streamed directly from
the Mac into `age` on the server; no plaintext or encrypted archive was left on
the Mac. Every archive was test-decrypted through `gzip -t` without extracting
it.

The parent path is server-only state outside the Syncthing-backed Documents
tree. It is included in the existing Backrest `/var/lib` backup source.

SHA-256 checksums:

```text
40b569a05ed5929ffc0b03d7228405a9c8e41cbc99d8e18e45cc2d19b2bef158  ssh-state.tar.gz.age
3fd2a3e1825961b294f33b5edd1bd45c8d7d06ed06859a85229b867f8ad6e391  tabby-state.tar.gz.age
6310bd24ba631437ee66557469a80ace72e9e22b68c014f6be3705b84eb75b9a  tailscale-machine-state.tar.gz.age
e5563319fd103bf54662473241599a7499cbba528c318556cb88bcf48a8cdd9c  tailscale-user-state.tar.gz.age
9ba0e42c7339021395d7bc9f252ae73b435ce8257d083b21fb64954ea57cc5ee  zen-state.tar.gz.age
```

These backups were taken while Zen and Tabby were running, so treat them as
crash-consistent snapshots. Before the eventual cutover, close each app from a
different terminal session and take a final quiescent backup if its most recent
writes matter.

The age recipient is derived from the server SSH host key:

`age1uj4ppzujd5jd2p4mh0hu9476zy0czhfr4hjl87gf2venl9cx4fzqzyn72a`

Decrypt on the server with the corresponding private host key. Never copy the
private key or decrypted archive to the Mac merely to inspect it.

## Pre-deployment review

1. Use a terminal other than Tabby for the cutover.
2. Confirm the encrypted recovery set is still readable.
3. Record the current app bundle locations.
4. Confirm the existing Tailscale connection works, but do not migrate,
   install, upgrade, restart, or remove Tailscale during this deployment.
5. Review any existing regular `~/.codex/config.toml`. Activation refuses to
   overwrite it; remove it deliberately only after confirming it is unused.
6. Run `just darwin-eval`. This evaluates only and does not build or activate.
7. Run a full remote build before switch. The pinned Zen and Tabby bundles are
   extracted on the Mac from signed, server-staged archives.

## Build-only validation

Build targets are exported independently so package failures can be isolated
without activating nix-darwin or launching either app. Codex is cross-compiled
for Apple silicon on Linux; the pinned application and Firefox CLI archives and
locked Tabby plugins are also realized there. Native archive extraction happens
on the Mac:

```sh
just darwin-build codex
just darwin-build tabby-plugins
just darwin-build firefox-cli
just darwin-build tabby
just darwin-build zen
just darwin-build macbook-system
```

`tabby`, `zen`, and `macbook-system` require a Darwin builder. The prebuilt
application paths perform native archive extraction and verify the original
Developer ID signatures. Building or copying these paths does not activate a
profile, launch an app, or read mutable app state.

Before inbound SSH is enabled, the Mac can pull a committed server-built
payload over its existing outbound SSH connection into an isolated temporary
directory:

```sh
scp nixos-pc:/srv/ops/hosts/macbook/build-from-mac /private/tmp/build-mac-apps
chmod 0700 /private/tmp/build-mac-apps
/private/tmp/build-mac-apps codex
```

Repeat the final command for `tabby-plugins` or `firefox-cli`. The helper refuses
a dirty server worktree, builds the Linux-hosted target on the server, and
prints the Mac staging path. Tabby, Zen, and Firefox CLI first require their
signed payloads to be copied with `just darwin-copy-apps`; their final Darwin
build targets then extract them natively.
None of these actions activates a profile, runs Homebrew, launches apps, or
reads mutable app profiles.

The helper can also build `tabby-source` or `macbook-system` locally from pinned
Git revisions. Those targets require the server-built inputs to be available
through an explicitly trusted signed-store path; do not weaken the daemon's
global trust settings to bootstrap them.

## Signed store transport

The server signing key is root-readable at
`/var/lib/homelab-nix-cache/macbook-1.sec`. Only its public key is committed in
`components/darwin-deploy/cache-public-key.txt`. The Mac trusts that public key
without adding the regular user to `trusted-users` or disabling signature
checks.

`components/darwin-deploy/artifacts.nix` records the five signed output paths
consumed by Darwin evaluation: Codex, Tabby plugins, the upstream Tabby ZIP,
the upstream Zen DMG, and the Firefox CLI archive. This
prevents the Mac from evaluating or realizing Linux build-tool derivations
merely to discover their output paths.
`hosts/macbook/copy-apps` refuses deployment if a newly built output does not
match the committed manifest.

Run `just darwin-prepare-artifacts` on the server after changing the manifest.
It verifies all five outputs and roots them under
`/srv/state/macbook-deploy/gcroots` so server garbage collection does not
discard them while Mac deployment is pending. It does not contact the Mac.

The one-time trust bootstrap changes only the installer-owned custom Nix
configuration and restarts the Nix daemon:

```sh
scp nixos-pc:/srv/ops/hosts/macbook/bootstrap-trust /private/tmp/bootstrap-trust
chmod 0700 /private/tmp/bootstrap-trust
sudo /private/tmp/bootstrap-trust
```

The first guarded activation verifies that this custom file still contains
only the expected server signing key. It then saves the file as
`/etc/nix/nix.custom.conf.before-nix-darwin` immediately before activation.
The Darwin configuration preserves Lix 2.95.2, the Lix binary cache and key,
the prompt prefix, and the substitute policy that the Lix installer placed in
`nix.conf`. The server signing key is also carried into the managed settings.
If the custom file differs from the known bootstrap result, deployment stops
without moving it.

Before inbound SSH is enabled, import all five signed payloads from the Mac:

```sh
scp nixos-pc:/srv/ops/hosts/macbook/pull-apps-from-mac /private/tmp/pull-mac-apps
chmod 0700 /private/tmp/pull-mac-apps
/private/tmp/pull-mac-apps
```

This populates `/nix/store` and creates staging GC roots under
`~/Library/Application Support/Homelab/nix-gcroots`. It does not create a
profile generation, install into `/Applications`, run Homebrew, launch an app,
or read an app profile.

## Existing deployment transport

The Darwin configuration declares key-only Remote Login and the server's SSH
key, but it does not declare Tailscale, PF rules, or a Tailscale package. The
deployment scripts use the Mac's existing network path without managing it.

The earlier one-time bootstrap installed and validated the current PF
restriction outside nix-darwin before enabling Remote Login:

```sh
scp nixos-pc:/srv/ops/hosts/macbook/bootstrap-tailscale-ssh /private/tmp/bootstrap-tailscale-ssh
chmod 0700 /private/tmp/bootstrap-tailscale-ssh
sudo /private/tmp/bootstrap-tailscale-ssh
```

After the Mac host key is pinned on the server, a store-only server push is:

```sh
cd /srv/ops
just darwin-copy-apps
```

Re-running the bootstrap is not part of normal Darwin deployment.

## Server-driven activation

The Linux server cross-builds Codex and packages the pinned application and
Firefox CLI archives, signs their Nix store paths, and copies them over the
tailnet. The remaining Darwin derivations extract the application bundles and
Firefox CLI package on the Mac from the committed server revision.
`hosts/macbook/deploy` then activates that exact result over SSH.

If activation stops after selecting the system profile but before creating
`/run/current-system`, correct the reported cause and rerun the guarded
deployment. The selected profile alone is an incomplete activation, and the
deployment helper safely selects the same or newer built result again.

On macOS 27, `/etc/pam.d/sudo_local` remains owned by macOS. The stock sudo
policy already includes this optional local file, and it is absent on this
Mac. nix-darwin's otherwise-default empty symlink is disabled because macOS 27
rejects creation at that protected path. No Touch ID, Watch ID, or PAM override
is enabled by this host configuration.

After the pre-deployment review:

```sh
cd /srv/ops
MACBOOK_DEPLOY_CONFIRM=deploy just darwin-deploy
```

Set `MACBOOK_SSH_HOST` or `MACBOOK_NIX_STORE` if the MagicDNS name differs. The
activation remains deliberately interactive and requires the explicit
`MACBOOK_DEPLOY_CONFIRM=deploy` guard plus Mac sudo authentication.

The workstation profile also installs `projectctl` with the Mac project root at
`/Users/rishabhgoel/Projects`. Project synchronization remains disabled until a
server manifest explicitly names the Mac and the separate sync deployment is
run:

```sh
projectctl sync enable <project> --target macbook
projectctl sync deploy macbook
```

The first command only edits project desired state. The second connects to the
Mac, refuses an unrelated non-empty destination, configures the independent
Syncthing folder on both devices, and preserves files when relationships are
later removed.

The same project catalog drives VSCodium:

```sh
vscodium-env list
projectctl ide <project>
projectctl ide fall-2026 \
  --cwd cmsc216 \
  --preset cmsc216
```

Managed projects may declare `[editor].preset` in `project.toml`; `general` is
the default and opens the matching server path over SSH. Set `local` for a
project that should open from the Mac's project tree. The remote application
provides **Projects: Open Project**, backed directly by the server's
`projectctl list --json`. `VSCodium 216` continues to open its fixed generated
course workspace so all CMSC 216 tasks remain available.

## Application cutover

Launch the Nix-managed Zen from `/Applications/Nix Apps`, install the packaged
FF-CLI Bridge XPI into that browser, and approve its pairing. Run
`zen-firefox-cli doctor` from the server, and verify a tab snapshot. The user's
separate, non-Nix Zen installation is outside this deployment. Preserve Tabby's
existing state when checking its Nix-managed app.

Tailscale remains outside this configuration after the application cutover.
Any future Tailscale package or Serve/Funnel migration must be designed,
backed up, reviewed, and deployed as a separate project.
