# Server Ops

This repo is the source of truth for the `nixos-pc` NixOS server.
It is intended to live in a private GitHub repository because it contains
infrastructure topology. Runtime secrets are intentionally kept out of GitHub.

The intended operating model is:

- NixOS flakes own durable host configuration.
- Caddy owns HTTP routing.
- Cloudflare Tunnel owns public ingress for `therealrishabh.com` and `*.therealrishabh.com`.
- `cfctl`, `wrangler`, and `flarectl` own Cloudflare command-line control.
- Tailscale plus CoreDNS own private ingress for `*.internal.therealrishabh.com`.
- Docker owns lab and CUDA workloads.
- sops-nix owns runtime secrets from the local-only `/home/rishabh/.config/homelab/secrets.yaml`.
- Apple Passwords and Vaultwarden own human credentials.

Common commands:

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
just workspace-sync
just public-site-deploy
just github-profile-sync
just rollback
```

Secret-dependent services are disabled by default. Bootstrap them in this order:

1. Install this repo at `/srv/ops`.
2. Configure sops recipients and create the local-only `/home/rishabh/.config/homelab/secrets.yaml`.
3. Enable `homelab.secrets`.
4. Enable ACME, Cloudflare Tunnel, private DNS, Vaultwarden, Backrest, Syncthing, and Samba as credentials become available.

See `runbooks/bootstrap.md` for the detailed first setup.
See `runbooks/cloudflare.md` for Cloudflare admin CLI setup.
See `runbooks/backups.md` for Restic backups to a Hetzner Storage Box.
See `runbooks/bitwarden-sops.md` for selectively promoting Vaultwarden secrets into sops.
See `runbooks/codex.md` for the managed Codex server integration.
See `runbooks/computer-use.md` for temporary Codex-controlled desktops.
See `runbooks/remote-phone.md` for bounded Pixel microphone capture and local transcription.
See `runbooks/canvas-bridge.md` for the private UMD Canvas mirror and Codex connector.
See `runbooks/workspace.md` for the shared Codex workspace.
See `runbooks/beeper.md` for exposing Beeper Desktop MCP to Codex over the tailnet.
See `runbooks/syncthing.md` for private Finder-friendly file sync setup.

`/srv/ops` should contain stateless infrastructure and operational knowledge.
User-owned source material lives under `/home/rishabh`: the editable public site
is `/home/rishabh/Projects/public-site`, the resume is
`/home/rishabh/Documents/resume`, and the public GitHub profile source is
`/home/rishabh/Documents/github-profile/README.md`. `just public-site-deploy`
copies the public site and resume PDF into `/srv/state/public-site`, while old
resume URLs redirect to `/rishabh-goel-resume.pdf`.
