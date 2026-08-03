# Codex

This directory contains the ops-owned desired state for the server's Codex
integration.

- `config.toml` is the Codex config seeded into `/srv/state/codex`; enabled
  plugin blocks in this file are installed during bootstrap.
- `AGENTS.md` is the Codex-specific guidance seeded into `/srv/state/codex`.
  It points server-aware chats at the generated `/home/rishabh/Agent` cockpit
  and the harness-neutral policy under `/srv/ops/agents`.
- `plugins/` is reserved for local plugin source owned by this repository.
- `.agents/plugins/marketplace.json` is the repo-local Codex plugin marketplace
  used by bootstrap for Homelab-owned plugins.

Prefer wrapping durable MCP integrations as local plugins instead of adding
top-level `mcp_servers` entries. Use direct MCP config only for short-lived
experiments or when a plugin wrapper would add no durable value.

Live Codex state, sessions, caches, auth materialization, and installed plugin
artifacts belong under `/srv/state/codex`.

Codex may create internal cache paths such as `.tmp/plugins/.agents` beneath
`/srv/state/codex`; those are runtime state, not ops repository source.
