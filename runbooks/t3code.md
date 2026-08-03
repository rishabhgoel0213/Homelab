# T3 Code and Pi

T3 Code is the tailnet-only web UI for the server's managed Codex and Pi
providers:

```text
https://t3code.internal.therealrishabh.com
```

The service is declarative in `modules/services/t3code.nix`. It binds only to
`127.0.0.1:3773`; Caddy publishes it through the existing internal wildcard
certificate and CoreDNS/Tailscale route.

## Managed state

- T3 Code: `/srv/state/t3code`
- Codex: `/srv/state/codex`
- Pi: `/srv/state/pi/agent`

T3 Code's Codex provider explicitly uses `/run/current-system/sw/bin/codex`
and `/srv/state/codex`, so the same authentication, plugins, and prior Codex
sessions used by direct Codex invocations are visible in T3 Code.

Pi uses `/run/current-system/sw/bin/pi` with `PI_CODING_AGENT_DIR` set to
`/srv/state/pi/agent`. Pi credentials, sessions, skills, extensions, prompts,
and future customizations therefore persist in one managed location. Pi MCP
integration is intentionally not configured yet.

## Remote browser preview

The web UI's Browser tab is backed by the managed Computer Use runtime. T3
advertises the capability only when both `T3CODE_REMOTE_PREVIEW_COMMAND` and
`T3CODE_REMOTE_PREVIEW_VIEWER_BASE_URL` are configured. Each T3 thread maps to
one deterministic `t3-<thread-id>` desktop:

```text
T3 Browser panel -> authenticated frame/input RPC -> Chromium page CDP
T3 preview_* tools -------------------------------> the same Chromium page
Codex Computer Use MCP -> managed thread desktop -> the same Chromium page
```

The embedded panel streams only page contents, so T3 owns the visible tab and
navigation chrome and sizes the browser viewport to the panel. The noVNC route
remains tailnet-only for full-desktop debugging, but is not embedded in T3.
The desktop launcher keeps CDP on loopback. Pi does not receive the Computer
Use MCP yet.

## Private source pin

The package builds the exact revision declared by
`homelab.t3code.revision` from the canonical private checkout at
`/home/rishabh/Projects/t3code`. Nix reads the committed Git tree, so uncommitted
working-tree changes do not enter the build.

To publish and deploy a new fork revision:

1. Commit and push it from `/home/rishabh/Projects/t3code`.
2. Set `homelab.t3code.revision` to the new 40-character commit in
   `hosts/nixos-pc/default.nix`.
3. Update `packages/t3code.nix`'s `pnpmDeps.hash` if the lockfile changed.
4. Run `just check`, `just build`, and `just switch` from `/srv/ops`.

## Operations

```bash
just t3code-doctor
just t3code-pair
just t3code-status
just t3code-logs
codex-desktop list
```

`just t3code-pair` mints a ten-minute pairing token. Open the internal URL and
enter that token when prompted; the command's localhost URL and QR code refer
to the same server but are not the normal tailnet entrypoint.

T3 Code has its own pairing/access controls. Do not publish this route through
the public Cloudflare ingress lane.
