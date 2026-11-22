# Zen Space Router

Automatically organizes newly opened tabs in Zen Browser into the matching Zen
Space using TypeSafe AI's Jev (`jev-latest`) System One decision model.

## Architecture

1. **Server (`nixos-pc`):** `zen-space-router.service` runs `server.py` on
   `127.0.0.1:8129`, loads `jev-api-key` from SOPS via systemd `LoadCredential`,
   and publishes over Tailscale at
   `https://zen-router.internal.therealrishabh.com`.
   - Keeps a persistent HTTP/2 connection pool to `https://api.typesafe.ai/v1/systemone`.
   - Evaluates `target_space` (`choice`) and `should_move` (`noul`) in a single
     parallel forward pass.
   - Caches single-purpose hosts for 6 hours and multi-topic hosts (YouTube,
     Google Docs, GitHub, Reddit, search engines, etc.) by normalized page + title
     for 15 minutes.
2. **MacBook (`Zen.app`):** `components/zen/darwin.nix` force-installs the
   packaged `zen-space-router@homelab.internal` WebExtension from the Nix store
   without modifying `Zen.app`'s vendor-signed bundle.
   - Uses a privileged WebExtension Experiment API (`zenSpaces`) to read live
     Zen Spaces and move tabs via `gZenWorkspaces.moveTabToWorkspace`.
   - Yields automatically to pinned, essential, glance, split-view, and native
     manual Zen Space Routing rules.
   - Toolbar popup lets you pause/resume routing, toggle following the active
     tab, pin specific hosts, inspect latency/confidence history, and edit
     per-Space routing criteria.

## Verification

- Server health: `curl -sf https://zen-router.internal.therealrishabh.com/health`
- Unit & packaging checks: `just check`
- After Mac activation, restart Zen once so enterprise policy picks up the new
  `ExtensionSettings` entry; the **Zen Space Router** icon appears in the toolbar.
