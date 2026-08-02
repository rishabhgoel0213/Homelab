# Codex Runbook

Codex is managed as a first-class homelab service.

```text
/srv/ops/codex      desired Codex config and plugin source
/srv/state/codex    live Codex runtime state
```

The systemd service uses the Nix-provided `codex` package and sets
`CODEX_HOME=/srv/state/codex`.

Codex-owned implementation caches can include paths such as
`/srv/state/codex/.tmp/plugins/.agents`. That is acceptable as runtime state.
The ops repository carries only the local plugin marketplace source at
`/srv/ops/codex/.agents/plugins/marketplace.json`.

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

`codex-bootstrap` seeds config, restores auth from `/run/secrets`, registers
the local plugin marketplace, and installs enabled plugins declared in
`/srv/ops/codex/config.toml`. The curated Cloudflare plugin owns the Cloudflare
API MCP server.

Durable MCP integrations should normally be wrapped as plugins in
`/srv/ops/codex/plugins` and exposed through the `homelab-local` marketplace.
Top-level `[mcp_servers.*]` config is reserved for short-lived experiments or
cases where a plugin wrapper would add no durable value.

`codex-update` updates the repo-owned Codex package override in
`/srv/ops/packages/codex.nix` to the latest stable upstream `rust-v*` tag and
refreshes the fixed-output source and Cargo vendor hashes.

`codex-auto-update` runs the same package update and switches the NixOS
generation only when the package file changes. It does not restart
`codex-remote-control.service`; restart that service manually when you want the
running Codex process to move to the new package. The systemd timer
`codex-auto-update.timer` runs it every morning at 04:30.

`codex-prune-user-install` removes the legacy `~/.local/bin/codex` shim when it
points into `~/.codex`. If no running process still has files open in
`~/.codex`, it syncs durable session data into `/srv/state/codex` and deletes
the legacy home.
