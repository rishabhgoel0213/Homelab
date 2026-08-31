# MacBook nix-darwin migration

No Mac generation was built or activated while this configuration was added.
Do not run the deployment command from an active Tabby session until the Tabby
replacement path has been tested from another terminal.

## Managed boundary

- The active MacBook profile uses server-cross-compiled Zen and the pinned
  upstream Tabby archive. Linux builds Zen for `aarch64-apple-darwin` with the
  Firefox toolchain and a pinned Apple SDK, then signs and transfers its Nix
  output. The Mac only copies the finished Zen bundle, applies an ad-hoc code
  signature, and verifies it; Firefox is never compiled on the Mac.
- The pinned Zen input lives in `/home/rishabh/Projects/zen-browser`; Tabby's
  source input lives in `/home/rishabh/Projects/tabby`. Commit source changes
  and run `just darwin-lock-sources` to update either lock. Zen's `prebuilt`
  package source remains available as a rollback option.
- Zen profile data and Tabby configuration remain mutable in their normal
  macOS application-support locations. They are not copied into the Nix store.
- Zen's Bitwarden extension is force-installed by enterprise policy in both
  package variants. Add future browser extensions to the corresponding policy
  in `components/zen/darwin.nix`. The policy uses Mozilla's supported macOS
  system preference domain and does not modify the signed application bundle.
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
7. Run a full remote build before switch. Zen is compiled for Apple silicon on
   the Linux server; Tabby's selected prebuilt bundle is extracted on the Mac.

## Build-only validation

Build targets are exported independently so package failures can be isolated
without activating nix-darwin or launching either app. Codex and Zen are
cross-compiled for Apple silicon on Linux; the pinned application archives and
locked Tabby plugins are also realized there. Native archive extraction and
Zen's final ad-hoc signature happen on the Mac:

```sh
just darwin-build codex
just darwin-build tabby-plugins
just darwin-build tabby
just darwin-build zen
just darwin-build macbook-system
```

`tabby`, `zen`, `macbook-system`, and `tabby-source` require a Darwin builder.
`zen-source` is the completed Linux cross-build payload; the selected Darwin
system wraps it with policy and an ad-hoc signature. The prebuilt paths perform
only native archive extraction and verify the original Developer ID
signatures. Building or copying any of these paths does not activate a profile,
launch an app, or read mutable app state.

Before inbound SSH is enabled, the Mac can pull a committed server-built
payload over its existing outbound SSH connection into an isolated temporary
directory:

```sh
scp nixos-pc:/srv/ops/hosts/macbook/build-from-mac /private/tmp/build-mac-apps
chmod 0700 /private/tmp/build-mac-apps
/private/tmp/build-mac-apps codex
```

Repeat the final command for `tabby-plugins` or `zen-source`. The helper refuses
a dirty server worktree, builds the Linux-hosted target on the server, and
prints the Mac staging path. Tabby and both Zen variants first require their
signed payloads to be copied with `just darwin-copy-apps`; their final Darwin
build targets then extract or wrap them natively.
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
the upstream Zen DMG, and the Linux-cross-compiled Zen application. This
prevents the Mac from evaluating or realizing Linux build-tool derivations
merely to discover their output paths.
`hosts/macbook/copy-apps` refuses deployment if a newly built output does not
match the committed manifest.

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

The Linux server cross-builds Codex and Zen and packages the upstream fallback
archives, signs their Nix store paths, and copies them over the tailnet. The
remaining Darwin derivations natively extract vendor-signed bundles or ad-hoc
sign the source-built Zen bundle on the Mac from the committed server revision.
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

## State-preserving application cutover

Do not delete Zen or Tabby profiles. First launch the Nix app from
`/Applications/Nix Apps` and verify the expected profile/config appears. If
macOS chooses a new profile because a bundle identifier changed, stop and map
the old profile explicitly rather than importing or overwriting it blindly.

Only after both apps have passed a launch/state check should their old app
bundles or package receipts be removed. Removing an app bundle must remain
separate from removing its profile data.

Tailscale remains outside this configuration after the application cutover.
Any future Tailscale package or Serve/Funnel migration must be designed,
backed up, reviewed, and deployed as a separate project.
