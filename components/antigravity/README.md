# Antigravity

Google's Antigravity CLI (`agy`) is installed alongside Codex and Claude Code.
T3 Code's Antigravity provider uses a separate Google runtime, the ACP server,
pinned here as well. Activation merges MCP definitions and global rules and
preserves credentials, preferences and sessions. It does not sign you in.

## State

`agy` always uses `$HOME/.gemini`. On the server, activation links
`/home/rishabh/.gemini` to `/srv/state/antigravity`, so its state lives under
`/srv/state` like Claude's. Activation never replaces an existing `~/.gemini`;
it warns if the link is missing. Settings are in
`~/.gemini/antigravity-cli/settings.json`.

T3 keeps its own per-instance Antigravity profiles (`GEMINI_HOME`) under
`/srv/state/t3code`, so T3 and terminal sign-ins are separate.

## Initial login

Terminal:

```sh
ssh -t rishabh@nixos-pc
cd /home/rishabh/Projects/Homelab
agy
```

Follow the Google sign-in prompt in that terminal. In T3, open Settings →
Providers → Antigravity and choose **Sign in with Google**. Activation enables
the provider once and points it at `/run/current-system/sw/bin/agy-acp-server`;
if you disable it in T3 later, activation leaves it disabled. No T3 restart is
required.

On the Mac, run `agy` and sign in separately. Credentials are not copied between
hosts.

## Updates and Mac delivery

`antigravity-auto-update.timer` runs daily at 06:30, after T3's 06:00 update.
It uses the shared Homelab lock and the clean-checkout/commit/push/deploy flow.

- The CLI follows Google's latest manifests for `linux_amd64` and
  `darwin_arm64`. Both must report the same version, and their sha512 values
  are pinned in `release.nix`.
- The ACP runtime follows the pinned T3 build. T3 accepts only exact, tested
  runtime versions, so `update.py` reads the linux-x64 URL and sha256 bundled in
  `.#t3code`. If T3 moves to a new runtime, the next run re-pins it. T3 keeps
  older tested versions supported, so the gap is harmless.

Validation failure restores unchanged candidate pins. A fresh Brick check is
required before release edits; privileged deployment remains broker guarded.

The server publishes a signed Mac Nix output with `just antigravity-publish-mac`.
The Mac's `antigravity-update` launch agent checks every 30 minutes and at login.
It verifies the server signature, Google's Developer ID signature and the CLI
version before atomically selecting a profile; previous generations remain
available. Running sessions are not restarted. After the initial Darwin
activation, binary updates do not require another full activation.

`agy` has no documented switch to disable its background self-updater. Its
binary is in the read-only Nix store, so it cannot replace itself; Nix pins are
the only update path.

## Runtime notes

- The ACP server's `.par` is an ELF stub with an appended Python archive.
  Patching would corrupt it, so it is installed unmodified and runs through
  nix-ld, which this module enables. `localharness_external` is static.
- T3 needs Node.js on its service PATH for Antigravity; the T3 module provides it.

## MCP and rules

`~/.gemini/config/mcp_config.json` is merged from Codex's checked-in
`mcp_servers` and the UMD Canvas plugin's `.mcp.json`, like Claude's. Stdio
servers keep `command`/`args`/`env`; HTTP servers use `serverUrl`/`headers`.
Codex-only policy keys are omitted. The shared agent policy is installed as the
global rule `~/.gemini/config/AGENTS.md`. The Mac gets neither, matching Claude.

Checks: `just check`, Linux system build, `just darwin-eval`, native CLI probes.
End-to-end model requests require Google sign-in.
