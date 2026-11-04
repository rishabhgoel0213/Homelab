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
AGENTS.md     consolidated agent guidance and the development/deployment workflow
```

Keep a service's package, module, helper commands, tests, configuration, and
runbook together under `components/<name>/`. Host files compose those modules;
they do not own reusable service implementation.

Start infrastructure sessions in `/home/rishabh/Projects/Homelab`, the development
clone of this repository. `/srv/ops` is the deployment checkout. All guidance from
the retired `agents/` workspace is consolidated in [AGENTS.md](AGENTS.md), which
Nix also installs as `/etc/agents/AGENTS.md`. The retired directory is removed.

Edit and commit in Homelab, then run `just deploy`: validate the clean commit,
push origin/main, fast-forward `/srv/ops` to the same commit, and activate it.
Dirty or diverged checkouts are rejected. Codex, Pi, and T3 automatic updates
use this same flow, defer while a checkout is dirty, and share its lock.

## Common commands

```bash
just build
just deploy
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
- [Agent workflow and environment](AGENTS.md)
- [Durable projects](components/projects/README.md)
- [Syncthing](components/syncthing/README.md)

## Repository boundaries

Homelab contains infrastructure code and operational documentation; `/srv/ops`
receives its committed deployment history. Personal source material remains in
the appropriate other projects or Documents, outside this repository. Service
runtime data stays under `/srv/state`.
