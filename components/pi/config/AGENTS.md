# Server Pi Guidance

This Pi home is managed by Homelab. Pi's durable agent directory is
`/srv/state/pi/agent`; do not create a second global Pi home under the user's
home directory.

## Server Context

- Agent sessions should run in durable projects under `/home/rishabh/Projects`
  (use `/home/rishabh/Projects/Homelab` for infrastructure).
- Read `/etc/agents/AGENTS.md` before server,
  NixOS, Cloudflare,
  Tailscale, backup, route, or service work.
- Route durable infrastructure work to `/home/rishabh/Projects/Homelab`, software projects to
  `/home/rishabh/Projects`, and durable documents to `/home/rishabh/Documents`.
- Edit and commit configuration in Homelab, then `just deploy` to push,
  fast-forward `/srv/ops`, and activate it. `/srv/state` remains runtime state.

## Pi Configuration

- Edit global Pi guidance and settings in `/home/rishabh/Projects/Homelab/components/pi/config`.
- The managed runtime Pi agent directory is `/srv/state/pi/agent`.
- Pi sessions, credentials, extensions, skills, prompts, and models belong
  under the managed agent directory.
- Do not add Codex MCP configuration to Pi. Pi integrations are managed
  independently and will be added deliberately later.

## Secrets

- Runtime secrets stay outside Git in
  `/home/rishabh/.config/homelab/secrets.yaml`, encrypted with SOPS.
- Never print, commit, or copy secret values into agent policy or task output.
