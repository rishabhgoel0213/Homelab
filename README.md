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

## Repository layout

The repository is organized by ownership rather than by file type:

```text
hosts/        host entry points and host-specific operations
profiles/     reusable compositions of components
platform/     shared NixOS and nix-darwin foundations
components/   vertically owned packages, modules, config, scripts, tests, docs
routes/       declarative routes and route-management commands
lib/          shared implementation libraries
tools/        repository-wide operator tooling
docs/         cross-cutting architecture, bootstrap, recovery, and security docs
agents/       the intentional agent-launch workspace and its policy files
```

Keep a service's package, module, helper commands, tests, configuration, and
runbook together under `components/<name>/`. Host files compose those modules;
they do not own reusable service implementation.

`/srv/ops/agents` intentionally remains a simple directory from which agents
can be launched with the repository's `AGENTS.md`, environment, and memory
guidance immediately available. It is not a component and must not be moved
under `components/` while that workflow is in use.

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
just local-model-use bonsai-ternary-27b
just local-model-doctor mach1-additive-35b
just project-list
just project-create linear-algebra
just project-session linear-algebra codex
just project-jupyter linear-algebra
just blog-build
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

- [First-time setup](docs/bootstrap/server.md)
- [Notebook blog](components/blog/README.md)
- [Cloudflare administration](components/cloudflare/README.md)
- [Backups](docs/recovery/backups.md)
- [Vaultwarden and sops](docs/security/bitwarden-sops.md)
- [Codex integration](components/codex/RUNBOOK.md)
- [T3 Code and Pi](components/t3code/README.md)
- [Local models in Pi](components/local-models/README.md)
- [Remote Phone microphone capture](components/remote-phone/README.md)
- [UMD Canvas bridge](components/canvas-bridge/README.md)
- [Agent environment](agents/RUNBOOK.md)
- [Durable projects](components/projects/README.md)
- [Syncthing](components/syncthing/README.md)

## Repository boundaries

`/srv/ops` contains infrastructure code and operational documentation. Personal
source material remains under `/home/rishabh`, outside this repository. Deploy
commands copy only the required build output into `/srv/state`.
