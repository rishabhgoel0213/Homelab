# Codex Computer Use

This server integrates
[`iFurySt/open-codex-computer-use`](https://github.com/iFurySt/open-codex-computer-use)
as a Nix-managed Computer Use runtime for temporary Linux desktops.

The durable source lives in `/srv/ops`; runtime desktops and logs live under:

```text
/srv/state/codex/computer-use
```

## Architecture

Codex sees one stable MCP server through the repo-owned `open-computer-use`
plugin:

```toml
[plugins."open-computer-use@homelab-local"]
enabled = true
```

The plugin's bundled MCP config points at
`/run/current-system/sw/bin/codex-computer-use-mcp`.

That broker owns temporary desktop capsules:

```text
Codex
  -> codex-computer-use-mcp
    -> codex-desktop start/list/stop
      -> Xvfb + DBus + AT-SPI + openbox + x11vnc + noVNC
      -> loopback-only Chromium DevTools Protocol for T3 preview automation
      -> open-computer-use mcp inside that desktop session
```

The important rule is that `open-computer-use` runs inside the graphical session
it controls. Do not run it as a detached system service and expect it to see
arbitrary VNC sessions.

## Desktop Hub

The human takeover UI is served at:

```text
https://desktops.internal.therealrishabh.com
```

`codex-desktop-hub.service` binds to `127.0.0.1:8765`, reads the same desktop
manifests as the MCP broker, and proxies each desktop's local noVNC listener
through stable paths:

```text
/desktop/<desktop-id>/
```

Use the hub to start a browser, terminal, or blank desktop, open the live noVNC
view, stop sessions, and prune stopped session directories. The route is
internal-only through Caddy and Tailscale DNS; the per-desktop VNC/noVNC ports
still stay bound to localhost.

## Commands

Start a browser desktop:

```bash
codex-desktop start
```

Start or reuse a deterministic browser desktop:

```bash
codex-desktop start --reuse --id t3-<thread-id> --profile browser
```

Browser manifests include `cdpUrl` and `cdpPort`. Both are loopback-only and
are intended for trusted server-side automation, not direct network exposure.

Start a blank desktop:

```bash
codex-desktop start --profile blank
```

Start a custom command inside the desktop:

```bash
codex-desktop start --profile none -- chromium --no-first-run about:blank
```

List desktops:

```bash
codex-desktop list
codex-desktop list --json
```

Inspect one desktop:

```bash
codex-desktop status <desktop-id>
codex-desktop env <desktop-id>
codex-desktop screenshot --output /tmp/desktop.png <desktop-id>
```

Run a command in the desktop session:

```bash
codex-desktop exec <desktop-id> -- open-computer-use call list_apps
```

Stop a desktop:

```bash
codex-desktop stop <desktop-id>
```

Remove stopped or exited runtime directories:

```bash
codex-desktop prune
```

## MCP Tools

The broker exposes lifecycle tools:

- `desktop_start`
- `desktop_list`
- `desktop_status`
- `desktop_vnc_url`
- `desktop_stop`

It also proxies the Open Computer Use tools into the selected desktop:

- `list_apps`
- `get_app_state`
- `click`
- `perform_secondary_action`
- `scroll`
- `drag`
- `type_text`
- `press_key`
- `set_value`

`get_app_state` keeps the upstream Open Computer Use accessibility tree as the
semantic source of truth and adds a PNG screenshot captured from the desktop's
Xvfb framebuffer when upstream does not return image content. This means Codex
can still see arbitrary applications visually even when an app exposes a weak
AT-SPI tree.

`press_key` is handled by the broker with `xdotool` inside the selected desktop
environment. The upstream Open Computer Use key mapper is useful when available,
but this direct X11 fallback keeps common key presses such as `Return`, `Tab`,
and `ctrl+l` working consistently in temporary desktops.

If a Computer Use tool is called without `desktop_id` and exactly one desktop is
running, that desktop is used. If no desktop is running, the broker starts a
browser desktop automatically. If multiple desktops are running, pass
`desktop_id` explicitly.

When `CODEX_COMPUTER_USE_DEFAULT_DESKTOP_ID` is set, that deterministic desktop
takes precedence over both the single-desktop heuristic and any desktop id an
agent supplies. `desktop_start` also reuses that managed id. T3 sets it on Codex
sessions so Computer Use controls the same thread-bound browser rendered by the
T3 Browser panel instead of silently creating a second desktop.

## Verification

After switching the NixOS generation:

```bash
codex-desktop start --json
codex-desktop list
codex-desktop exec <desktop-id> -- open-computer-use call list_apps
codex-desktop stop <desktop-id>
```

For MCP-level validation, restart `codex-remote-control.service` after the new
config is seeded and ask Codex to call `desktop_start`, then `list_apps`.

## Network Notes

The desktop's VNC and noVNC listeners bind to `127.0.0.1` by default. This keeps
temporary desktops private to the server, Codex process, and desktop hub. Human
takeover should normally go through
`https://desktops.internal.therealrishabh.com` instead of exposing random noVNC
ports.

Do not expose these temporary desktops publicly without authentication.
