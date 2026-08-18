# Server Codex Guidance

This Codex home is managed by `/srv/ops`. The source for this file is
`/srv/ops/codex/AGENTS.md`; the runtime copy lives at
`/srv/state/codex/AGENTS.md`.

## Server Context

- Agent sessions should run in durable projects under `/home/rishabh/Projects`
  or another canonical repository such as `/srv/ops`.
- Read `/etc/agents/AGENTS.md` and `/etc/agents/ENVIRONMENT.md` before server,
  NixOS, Cloudflare,
  Tailscale, Codex, backup, route, or service work.
- Route work to `/srv/ops`, `/home/rishabh/Projects`, or
  `/home/rishabh/Documents`. Use `projectctl create <name>` when a new project
  is needed.
- Treat `/srv/ops` as the source of truth for durable server configuration.
- Treat `/srv/state` as runtime state. Do not edit service state directly unless
  a runbook calls for it or the user explicitly asks.
- For authorized signup, login, and verification workflows, create a scoped
  inbox with `singlemail create --purpose "..." --ttl 1h --json`, then use
  `singlemail code` or `singlemail links`. Promote the inbox before relying on
  it for account recovery. Never use Singlemail to evade bans, account limits,
  identity checks, or site terms.

## Codex Configuration

- The desired Codex config is `/srv/ops/codex/config.toml`.
- The managed runtime Codex home is `/srv/state/codex`.
- Do not make durable config changes only in `/srv/state/codex`; update
  `/srv/ops/codex` and run the appropriate ops command instead.

## Secrets

- Runtime secrets are outside Git in
  `/home/rishabh/.config/homelab/secrets.yaml`, encrypted with SOPS.
- Prefer the existing scripts such as `just secrets-edit`,
  `just cloudflare-store-token`, `just tailscale-store-oauth`, and
  `just codex-store-auth`.
- Never print, commit, or copy secret values into agent policy or task output.
