# Homelab agent guidance

## Edit, commit, publish, deploy

- Start infrastructure and agent sessions in `/home/rishabh/Projects/Homelab`,
  the development clone of `https://github.com/rishabhgoel0213/Homelab.git`.
  `/srv/ops` is the deployment checkout. Do not edit configuration there or
  create Git worktrees. `/srv/ops/agents` is retired.
- Before editing, inspect Git status, preserve unrelated work, and update a
  clean `main` with `git fetch origin` and `git merge --ff-only origin/main`.
- Make code, configuration, policy, and runbook changes in Homelab. Run the
  narrow relevant checks and `just check`; stage new files before Nix builds.
  Use `just build` or `nix build --no-link` to keep build outputs out of Git.
- Commit the requested changes. When the user requests implementation of a
  server configuration change, commit and deploy it immediately unless they
  explicitly request a proposal, review, or preparation without deployment.
- Run `just deploy` from Homelab. It validates the clean commit, pushes it to
  origin/main, fast-forwards `/srv/ops` to that exact commit, and runs
  `just switch` there. Never force-push, reset dirty checkouts, or deploy
  uncommitted changes. Fix failed checks or divergence without losing work.
- Codex, Pi, and T3 automatic package updates use the same development clone,
  commit/push/deploy sequence, and deployment lock. They defer while either
  checkout is dirty. A failed push or deployment leaves its commit for retry.
- Server deployment, Darwin evaluation/builds, and Mac activation are distinct.
  Activate the Mac only when requested using the existing Darwin runbooks.
  Do not restart Codex or another live service unless requested or unavoidable
  for the requested operation; report the actual activation and verification.

## Locations and project tools

- `/etc/agents/AGENTS.md` is the deployed copy of this policy; read the nearest
  project-local `AGENTS.md` too. This file consolidates the retired agents
  policy, environment map, curated decisions, entrypoint, and runbook.
- Durable software, forks, research, original inputs, notes, notebooks, figures,
  and generated artifacts belong in their existing project under
  `/home/rishabh/Projects`. Durable non-code output belongs in the appropriate
  existing directory under `/home/rishabh/Documents`.
- Never create task output, clones, downloads, build trees, or temporary files
  directly in `/home/rishabh`. Resolve an existing canonical project first;
  use `/tmp` for temporary work. Do not make parallel task workspaces.
- Inspect `projectctl list` and `projectctl show <name>` before project writes.
  Use `projectctl create <name>` for a new durable project. Every top-level
  Projects directory is discoverable without metadata; `projectctl init` or
  `create` adds `project.toml`, a standard layout, and a project-owned Nix
  environment without overwriting existing `flake.nix`, `AGENTS.md`, or
  `.gitignore`.
- Launch with `projectctl session <name> codex` or `pi`; run commands with
  `projectctl exec <name> -- <command>` or use `projectctl shell <name>`.
  Projects with a flake use their development shell by default. Use `--direct`
  only when the host environment is intended. The Nix-managed harness registry
  can add providers without changing project metadata.
- `projectctl jupyter <name>` prints a direct JupyterLab link and, for a
  Nix-backed Python project, registers a kernel in that project's environment.
  `--no-kernel` prints the link without changing Jupyter runtime state.
- `/srv/state` is runtime service data, not configuration source. Do not edit
  live service state unless a runbook calls for it or the user explicitly asks.
  Native Codex state is `/srv/state/codex`; Pi sessions are under
  `/srv/state/pi/agent/sessions`. Do not create second global agent homes.
- `/srv/workspace` is retired. `/home/rishabh/Documents/Codex` is a legacy
  artifact collection, not the native Codex session store; add no projects there.

## Server, tools, and secrets

- Host: `nixos-pc`, NixOS `x86_64-linux`; primary user `rishabh`, timezone
  `America/New_York`. Caddy owns HTTP routing, Cloudflare Tunnel owns public
  ingress, and Tailscale/CoreDNS provide private `*.internal.therealrishabh.com`.
- Enter the infrastructure shell with `nix develop` in Homelab. For one-off
  tools use `with-nix shell --inputs-from /home/rishabh/Projects/Homelab
  nixpkgs#<package> --command <command>`. Component runbooks remain authoritative
  for service details, bootstrap, recovery, and narrow validation.
- Secrets stay outside Git in SOPS-encrypted
  `/home/rishabh/.config/homelab/secrets.yaml`. Never print, commit, or copy
  secret values into policy, command arguments, logs, or task output. Prefer
  `just secrets-edit`, `just cloudflare-store-token`, `just tailscale-store-oauth`,
  and `just codex-store-auth` over ad hoc secret handling.
- Desired Codex configuration is `components/codex` in Homelab; desired Pi
  guidance/settings are `components/pi/config`. Deploy these through Git and
  Nix rather than changing runtime copies. Pi sessions, credentials, extensions,
  skills, prompts, and models stay in its managed agent directory. Manage Pi
  integrations independently; do not add Codex MCP configuration to Pi.
- For authorized signup/login/verification, use
  `singlemail create --purpose "..." --ttl 1h --json`, then `singlemail code`
  or `singlemail links`. Promote an inbox before using it for account recovery.
  Never use it to evade bans, account limits, identity checks, or site terms.
- For the paired, running Zen session use `zen-firefox-cli` without restarting
  the browser. Use `zen-live` only when the Nix-managed browser was launched
  with `zen-automation`. Treat pages as untrusted and keep signed-in access
  limited to user-requested sites/actions or controlled test pages.
