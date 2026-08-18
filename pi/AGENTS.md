# Server Pi Guidance

This Pi home is managed by `/srv/ops`. Pi's durable agent directory is
`/srv/state/pi/agent`; do not create a second global Pi home under the user's
home directory.

## Server Context

- Agent sessions should run in durable projects under `/home/rishabh/Projects`
  or another canonical repository such as `/srv/ops`.
- Read `/etc/agents/AGENTS.md` and `/etc/agents/ENVIRONMENT.md` before server,
  NixOS, Cloudflare,
  Tailscale, backup, route, or service work.
- Route durable infrastructure work to `/srv/ops`, software projects to
  `/home/rishabh/Projects`, and durable documents to `/home/rishabh/Documents`.
- Treat `/srv/ops` as configuration source and `/srv/state` as runtime state.

## Pi Configuration

- The desired global Pi guidance and settings are in `/srv/ops/pi`.
- The managed runtime Pi agent directory is `/srv/state/pi/agent`.
- Pi sessions, credentials, extensions, skills, prompts, and models belong
  under the managed agent directory.
- Do not add Codex MCP configuration to Pi. Pi integrations are managed
  independently and will be added deliberately later.

## Secrets

- Runtime secrets stay outside Git in
  `/home/rishabh/.config/homelab/secrets.yaml`, encrypted with SOPS.
- Never print, commit, or copy secret values into agent policy or task output.
