# MacBook nix-darwin migration

No Mac generation was built or activated while this configuration was added.
Do not run the deployment command from an active Tabby session until the Tabby
replacement path has been tested from another terminal.

## Managed boundary

- Nix builds Zen and Tabby from the pinned server Git inputs in
  `/home/rishabh/Projects/zen-browser` and `/home/rishabh/Projects/tabby`.
  Commit source changes, then run `just darwin-lock-sources` to advance the
  flake lock to those revisions.
- Zen profile data and Tabby configuration remain mutable in their normal
  macOS application-support locations. They are not copied into the Nix store.
- Zen's Bitwarden extension is force-installed by enterprise policy in the app
  bundle. Add future browser extensions to `packages/zen-browser.nix`.
- Tabby's current third-party plugins are pinned in
  `tabby-plugins/package.json`. Add or update plugins there, regenerate the
  lockfile, and update the Nix dependency hash.
- Nix installs Codex CLI from `packages/codex.nix`. Codex.app itself remains
  unmanaged. Both intentionally share `~/.codex/config.toml` and auth state.
- Nix/Homebrew manages the official standalone `tailscale-app` package. Do not
  also enable nix-darwin's open-source `services.tailscale` module during this
  migration because it uses a different local service and state layout.

## Encrypted recovery set

The server-only recovery set is:

`/home/rishabh/Documents/system-migration-backups/20260822T053411Z-macbook`

It contains encrypted Zen, Tabby, SSH, Tailscale user state, and protected
`/Library/Tailscale` machine state. The archives were streamed directly from
the Mac into `age` on the server; no plaintext or encrypted archive was left on
the Mac. Every archive was test-decrypted through `gzip -t` without extracting
it.

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
3. Record the current app bundle locations and Homebrew/package receipts.
4. Confirm `/Library/Tailscale/profile-data` still exists. The first activation
   must not run `brew uninstall --zap`, because the cask's zap stanza deletes
   `/Library/Tailscale`.
5. Review any existing regular `~/.codex/config.toml`. Activation refuses to
   overwrite it; remove it deliberately only after confirming it is unused.
6. Run `just darwin-eval`. This evaluates only and does not build or activate.
7. Run a full remote build before switch. Zen is a large Firefox build and the
   first build can take a long time.

## Server-driven deployment

The Linux server cannot build Apple binaries locally. `scripts/deploy-macbook`
uses the Mac's Nix store as an `aarch64-darwin` remote builder, copies the exact
result back to the Mac, and activates it over SSH. The regular Mac user is not
made a global Nix trusted user.

After the pre-deployment review:

```sh
cd /srv/ops
MACBOOK_DEPLOY_CONFIRM=deploy just darwin-deploy
```

Set `MACBOOK_SSH_HOST` and `MACBOOK_NIX_BUILDER` if the MagicDNS name differs.
The first bootstrap may require a one-time, narrowly scoped Nix remote-builder
permission adjustment on the Mac; inspect the exact error before changing any
trust setting.

## State-preserving application cutover

Do not delete Zen or Tabby profiles. First launch the Nix app from
`~/Applications/Nix Apps` and verify the expected profile/config appears. If
macOS chooses a new profile because a bundle identifier changed, stop and map
the old profile explicitly rather than importing or overwriting it blindly.

Only after both apps have passed a launch/state check should their old app
bundles or package receipts be removed. Removing an app bundle must remain
separate from removing its profile data.

For Tailscale, verify the same tailnet node identity, MagicDNS reachability,
and SSH access before adding declarative Serve/Funnel rules. Keep Serve changes
in `modules/darwin/tailscale.nix` and review their exposure separately.
