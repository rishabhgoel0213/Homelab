# Codex Runbook

Codex is managed as a first-class homelab service.

```text
/srv/ops/components/codex      desired Codex config and plugin source
/srv/state/codex    live Codex runtime state
```

The systemd service uses the Nix-provided `codex` package and sets
`CODEX_HOME=/srv/state/codex`.

Codex-owned implementation caches can include paths such as
`/srv/state/codex/.tmp/plugins/.agents`. That is acceptable as runtime state.
The ops repository carries only the local plugin marketplace source at
`/srv/ops/components/codex/.agents/plugins/marketplace.json`.

The `homelab-local` marketplace registration is declared in
`/srv/ops/components/codex/config/server.toml`. Keep it there rather than registering it only in
the live Codex home: service startup replaces the runtime config from the
repo-owned copy, and the Apps UI cannot enumerate local plugins without the
marketplace registration even when their cached tools still work.

Useful commands:

```bash
just codex-store-auth
just codex-migrate-state
just codex-bootstrap
just codex-update
just codex-auto-update
just codex-prune-user-install
```

`codex-store-auth` stores the current Codex `auth.json` and MCP OAuth
credentials into the SOPS keys `codex-auth.json` and
`codex-credentials.json`. These are bootstrap and disaster-recovery snapshots.
When the Codex service starts, Nix restores them only if the corresponding
runtime file is missing or empty. Existing files in `/srv/state/codex` remain
authoritative because Codex rotates refresh credentials in place; overwriting
them from an older SOPS snapshot can restore an already-used token and force a
new login.

`codex-bootstrap` seeds config, restores auth from `/run/secrets` only when the
corresponding runtime file is missing or empty, registers the local plugin
marketplace, and installs enabled plugins declared in
`/srv/ops/components/codex/config/server.toml`. The curated Cloudflare plugin owns the Cloudflare
API MCP server.

Durable MCP integrations should normally be wrapped as plugins in
`/srv/ops/components/codex/plugins` and exposed through the `homelab-local` marketplace.
Top-level `[mcp_servers.*]` config is reserved for short-lived experiments or
cases where a plugin wrapper would add no durable value.

`just codex-update` pins the complete official Linux and provisioned Mac
release archives in `/srv/ops/components/codex/release.nix` to the latest
stable upstream `rust-v*` tag. Each archive hash covers all binaries, resource bundles, and package
metadata. Installation copies the entire archive, including future bundles;
there is no local allowlist of Cargo binaries or resource directories.
Nix patches ELF dependencies recursively and fails on unresolved dependencies.
Every package build verifies all archive entries and initializes the bundled
voice runtime without opening audio devices or connecting to a service.
Failed update builds restore the previous pin and Darwin artifact manifest
so the next run can retry. The Mac archive is packaged on Linux without
rewriting or re-signing upstream Mach-O files. It is not a source cross-build.

Use `nix build --impure --no-link .#codex` to validate the server package alone.
Use `nix build --impure --no-link .#macbook-codex` for the Mac package.

`codex-auto-update` runs the same package update and switches the NixOS
generation only when the package file changes. It does not restart
`codex-remote-control.service`; restart that service manually when you want the
running Codex process to move to the new package. The systemd timer
`codex-auto-update.timer` runs it every morning at 04:30.
After a successful switch (or a no-op), it runs `bin/publish-mac`, which
checks the artifact manifest, signs and verifies the Nix path with the
existing Mac deployment cache key, roots current/previous packages and
atomically writes `/srv/state/codex-mac-release/current.json`. A failed
publication can be retried with `just codex-publish-mac`; no Mac is contacted.

## Native Mac terminal and voice

After `MACBOOK_DEPLOY_CONFIRM=deploy just darwin-deploy`, run on the Mac:

```sh
codex-server -C /srv/ops
codex-server resume
codex-update
```

`codex-server` is a native Mac UI, not an SSH terminal running the Linux UI.
Its private, mode-0600 local Unix socket opens authenticated byte relays via
`rishabh@nixos-pc` to the existing app-server control socket. SSH executes a
small Python standard-library relay as rishabh; it requires the server's
existing `/run/current-system/sw/bin/python3`, not a new daemon or open port.
This also avoids Tailscale SSH's restrictions on direct Unix forwarding of
paths outside the user's home, `/tmp`, and `/run/user/<uid>`.
Each new connection gets a fresh SSH process; keepalives detect a dead link.
After a long sleep/network loss, reopen `codex-server resume` and `/voice`
if the upstream UI does not recover the voice call automatically.

Select `/voice`, approve the macOS microphone prompt, and choose the MacBook
microphone/speakers (or headphones) in the UI/system audio settings. The native
voice runtime handles capture, playback and echo processing. Nix deliberately
does not grant microphone/TCC consent, force audio-device choices, or capture
audio during deployment. Native permission, feedback and latency checks must
be done interactively after activation; Linux build checks cannot prove them.

`codex` still runs locally on the Mac; `codex-server` uses server auth, files,
tools and history. Use a server path with `-C`, not a `/Users/...` Mac path.
The existing server app-server is not restarted by package updates, preserving
active sessions. Restart `codex-remote-control.service` manually when ready
to move its backend to the newly installed version.

The Mac LaunchAgent `com.therealrishabh.codex-update` checks at login and every
30 minutes. It reads the server manifest over authenticated SSH, copies the
already-built Nix output, verifies the server cache signature and native Apple
signatures, then atomically changes a dedicated profile. Failed checks leave
the active profile unchanged. Existing clients continue running their original
binary. State and logs are under
`~/Library/Application Support/Homelab/codex/` (`update.log`, `update.err`).
Tailscale/SSH must already connect without an interactive password and with a
trusted host key; the updater never disables host verification or prompts in
the background. An offline Mac retries on the next interval.

For a rollback, unload the updater temporarily and use
`nix-env -p "$HOME/Library/Application Support/Homelab/codex/profile" --rollback`.
The immutable bootstrap package remains rooted by the Darwin system. A
`candidate` profile holds downloaded packages while signatures are checked;
it is never used to launch Codex. Do not run `nix-env` against the system
profile for routine Codex updates.

`codex-prune-user-install` removes the legacy `~/.local/bin/codex` shim when it
points into `~/.codex`. If no running process still has files open in
`~/.codex`, it syncs durable session data into `/srv/state/codex` and deletes
the legacy home.
