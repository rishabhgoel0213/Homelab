# MacBook nix-darwin migration

No Mac generation was built or activated while this configuration was added.
Do not run the deployment command from an active Tabby session until the Tabby
replacement path has been tested from another terminal.

## Managed boundary

- The active MacBook profile uses pinned upstream Zen and Tabby application
  bundles. Linux downloads, verifies, and packages them without compiling
  Electron or Firefox on the Mac.
- Source builds remain available as `zen-source` and `tabby-source`. Their
  pinned inputs live in `/home/rishabh/Projects/zen-browser` and
  `/home/rishabh/Projects/tabby`. Set the component's `packageSource` option to
  `source`, commit source changes, then run `just darwin-lock-sources` to swap
  one back in.
- Zen profile data and Tabby configuration remain mutable in their normal
  macOS application-support locations. They are not copied into the Nix store.
- Zen's Bitwarden extension is force-installed by enterprise policy in both
  package variants. Add future browser extensions to the corresponding policy
  in `components/zen/prebuilt-package.nix` and `components/zen/package.nix`.
- Tabby's current third-party plugins are pinned in
  `components/tabby/plugins/package.json`. Add or update plugins there, regenerate the
  lockfile, and update the Nix dependency hash.
- Nix installs the server-cross-compiled Codex CLI from
  `components/codex/cross-package.nix`. Codex.app itself remains unmanaged.
  Both intentionally share `~/.codex/config.toml` and auth state.
- Tailscale is outside the Darwin configuration. The existing standalone app,
  service, node identity, and local state remain unmanaged and untouched. The
  deployment scripts may use its existing network path only as transport.

## Encrypted recovery set

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
7. Run a full remote build before switch. The source variants remain optional;
   the selected prebuilt Zen and Tabby bundles do not trigger application
   compilation on the Mac.

## Build-only validation

Build targets are exported independently so package failures can be isolated
without activating nix-darwin or launching either app. Codex is cross-compiled
for `aarch64-darwin` on Linux; the prebuilt application bundles and locked
Tabby plugins are also realized on Linux:

```sh
just darwin-build codex
just darwin-build tabby-plugins
just darwin-build tabby
just darwin-build zen
just darwin-build macbook-system
```

Only `macbook-system`, `tabby-source`, and `zen-source` require a Darwin
builder. The selected Zen and Tabby bundles are ad-hoc re-signed on Linux so
their managed contents have a valid Apple code envelope. Building or copying
any of these paths does not activate a profile, install an app bundle, launch
an app, or read mutable app state.

Before inbound SSH is enabled, the Mac can pull a committed server-built
payload over its existing outbound SSH connection into an isolated temporary
directory:

```sh
scp nixos-pc:/srv/ops/hosts/macbook/build-from-mac /private/tmp/build-mac-apps
chmod 0700 /private/tmp/build-mac-apps
/private/tmp/build-mac-apps codex
```

Repeat the final command for `tabby-plugins`, `tabby`, and `zen`. The helper
refuses a dirty server worktree, builds the Linux-hosted target on the server,
and prints the Mac staging path. Staging does not import the payload into the
Mac's Nix store, activate a system profile, run Homebrew, install app bundles,
launch apps, or read mutable app profiles.

The helper can also build `tabby-source`, `zen-source`, or `macbook-system`
locally from pinned Git revisions. Those targets require the server-built
inputs to be available through an explicitly trusted signed-store path; do not
weaken the daemon's global trust settings to bootstrap them.

## Signed store transport

The server signing key is root-readable at
`/var/lib/homelab-nix-cache/macbook-1.sec`. Only its public key is committed in
`components/darwin-deploy/cache-public-key.txt`. The Mac trusts that public key
without adding the regular user to `trusted-users` or disabling signature
checks.

`components/darwin-deploy/artifacts.nix` records the four signed output paths
consumed by Darwin evaluation. This prevents the Mac from evaluating or
realizing Linux build-tool derivations merely to discover their output paths.
`hosts/macbook/copy-apps` refuses deployment if a newly built output does not
match the committed manifest.

The one-time trust bootstrap changes only the installer-owned custom Nix
configuration and restarts the Nix daemon:

```sh
scp nixos-pc:/srv/ops/hosts/macbook/bootstrap-trust /private/tmp/bootstrap-trust
chmod 0700 /private/tmp/bootstrap-trust
sudo /private/tmp/bootstrap-trust
```

Before inbound SSH is enabled, import all four signed payloads from the Mac:

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

The Linux server cross-builds Codex and packages the selected upstream app
bundles, signs them, and copies them over the tailnet. The remaining Darwin
derivations build locally on the Mac from the committed server revision.
`hosts/macbook/deploy` then activates that exact result over SSH.

After the pre-deployment review:

```sh
cd /srv/ops
MACBOOK_DEPLOY_CONFIRM=deploy just darwin-deploy
```

Set `MACBOOK_SSH_HOST` or `MACBOOK_NIX_STORE` if the MagicDNS name differs. The
activation remains deliberately interactive and requires the explicit
`MACBOOK_DEPLOY_CONFIRM=deploy` guard plus Mac sudo authentication.

## State-preserving application cutover

Do not delete Zen or Tabby profiles. First launch the Nix app from
`~/Applications/Nix Apps` and verify the expected profile/config appears. If
macOS chooses a new profile because a bundle identifier changed, stop and map
the old profile explicitly rather than importing or overwriting it blindly.

Only after both apps have passed a launch/state check should their old app
bundles or package receipts be removed. Removing an app bundle must remain
separate from removing its profile data.

Tailscale remains outside this configuration after the application cutover.
Any future Tailscale package or Serve/Funnel migration must be designed,
backed up, reviewed, and deployed as a separate project.
