# NixOS Homelab

My personal configuration for a NixOS homelab running on `nixos-pc`. It manages
the server, services, networking, backups, and integrations I use at home.
Runtime secrets and personal data are intentionally kept out of this repository.

## Architecture

- NixOS flakes define the host configuration.
- Caddy routes HTTP services.
- Cloudflare Tunnel provides public access to `therealrishabh.com` and its
  subdomains.
- `cfctl`, `wrangler`, and `flarectl` provide Cloudflare command-line access.
- Tailscale and CoreDNS provide private access through
  `*.internal.therealrishabh.com`.
- Docker runs lab and CUDA workloads.
- sops-nix loads runtime secrets from the local-only
  `/home/rishabh/.config/homelab/secrets.yaml`.
- Apple Passwords and Vaultwarden store human-managed credentials.

## Common commands

```bash
just build
just switch
just routes
just route-add demo public http://127.0.0.1:3000
just route-add vault internal http://127.0.0.1:8222
just cloudflare-store-token
just tailscale-store-oauth
just remote-phone-doctor
just remote-phone-check
just canvas-doctor
just canvas-pair
just t3code-doctor
just local-model-doctor mach1-additive-35b
just agent-index
just agent-work
just agent-gc
just public-site-deploy
just github-profile-sync
just rollback
```

## Initial setup

Services that require credentials are disabled by default. A new installation
can be bootstrapped in this order:

1. Install this repo at `/srv/ops`.
2. Configure sops recipients and create the local-only `/home/rishabh/.config/homelab/secrets.yaml`.
3. Enable `homelab.secrets`.
4. Enable ACME, Cloudflare Tunnel, private DNS, Vaultwarden, Backrest, Syncthing, and Samba as credentials become available.

## Runbooks

- [First-time setup](runbooks/bootstrap.md)
- [Cloudflare administration](runbooks/cloudflare.md)
- [Backups](runbooks/backups.md)
- [Vaultwarden and sops](runbooks/bitwarden-sops.md)
- [Codex integration](runbooks/codex.md)
- [T3 Code and Pi](runbooks/t3code.md)
- [Local models in Pi](runbooks/local-models.md)
- [Remote Phone microphone capture](runbooks/remote-phone.md)
- [UMD Canvas bridge](runbooks/canvas-bridge.md)
- [Agent environment](runbooks/agents.md)
- [Beeper Desktop MCP](runbooks/beeper.md)
- [Syncthing](runbooks/syncthing.md)

## Repository boundaries

`/srv/ops` contains infrastructure code and operational documentation. Personal
source material remains under `/home/rishabh`, outside this repository. Deploy
commands copy only the required build output into `/srv/state`.
