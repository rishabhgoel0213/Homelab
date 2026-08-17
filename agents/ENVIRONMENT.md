# Environment Map

## Canonical Paths

- `/etc/agents` - deployed harness-neutral policy and environment map.
- `/home/rishabh/Projects` - canonical software and research repositories.
- `/home/rishabh/Documents` - canonical durable personal documents.
- `/srv/ops` - declarative NixOS, homelab, Codex, and agent configuration.
- `/srv/state` - persistent runtime state, including native conversation data.
- `/srv/state/codex` - Codex sessions, authentication, plugins, and caches.
- `/var/tmp/agent-work` - manifest-managed, expiring task directories.

## Tooling

- Enter the server configuration shell with `nix develop /srv/ops`.
- Run one-off Nix tools with
  `with-nix shell --inputs-from /srv/ops nixpkgs#<package> --command <command>`.
- Run infrastructure checks from `/srv/ops` with `just check`, `just build`,
  `just test`, or another narrow recipe.

## Server Facts

- Host: `nixos-pc`, NixOS, `x86_64-linux`.
- Primary user: `rishabh`; time zone: `America/New_York`.
- Caddy owns HTTP routing, Cloudflare Tunnel owns public ingress, and Tailscale
  plus CoreDNS provide private `*.internal.therealrishabh.com` access.
- Runtime secrets are SOPS-encrypted outside Git at
  `/home/rishabh/.config/homelab/secrets.yaml`.

Detailed operational truth and runbooks remain in `/srv/ops`; this file is only
the stable routing map an agent needs before choosing a working directory.
