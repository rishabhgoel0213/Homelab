# Codex

This directory contains the ops-owned desired state for the server's Codex
integration.

The server package installs the complete official Codex release archive,
including package metadata and all resource bundles. The daily updater pins
both platform archive hashes in `release.nix`, rather than maintaining a list
of binaries to compile. The Mac payload is the complete upstream-provisioned,
Apple-signed release, packaged on Linux without modifying Mach-O files.
Package builds check archive completeness and initialize the voice runtime.

The server updater prepares both platforms, and `bin/publish-mac` signs and
publishes the Mac Nix output. A Mac user LaunchAgent checks every 30 minutes
and at login. `codex-update` triggers the same check immediately. Updates
verify Nix and Apple signatures before atomically selecting a user profile;
they do not require sudo or replace running Codex processes.

- `config/server.toml` is the Codex config seeded into `/srv/state/codex`; enabled
  plugin blocks in this file are installed during bootstrap.
- `config/macbook.toml` is the immutable config shared by the Nix-managed CLI
  and unmanaged Codex.app. It contains only declarative settings; clients must
  not try to edit the Nix-store target in place.
- `AGENTS.md` is the Codex-specific guidance seeded into `/srv/state/codex`.
  It points server-aware chats at the deployed harness-neutral policy under
  `/etc/agents` and at durable projects under `/home/rishabh/Projects`.

Prefer plain CLIs (`tasks`, `canvas-bridge`, etc.) over harness-specific MCP
servers or local Codex plugins so every agent harness shares the same tools.

Live Codex state, sessions, caches, auth materialization, and installed plugin
artifacts belong under `/srv/state/codex`.

Codex may create internal cache paths such as `.tmp/plugins/.agents` beneath
`/srv/state/codex`; those are runtime state, not ops repository source.
