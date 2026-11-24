# Claude Code

Claude Code is installed alongside Codex. T3 uses the managed absolute launcher,
with `/srv/state/claude` as its home. Terminal and T3 sessions on the server use
that same persistent login. Activation merges MCP definitions and preserves
credentials, preferences and sessions. It does not sign you in automatically.

## Initial login

From your terminal:

```sh
ssh -t rishabh@nixos-pc
cd /home/rishabh/Projects/Homelab
claude auth login
claude auth status
```

Open the printed URL on your own browser and finish the flow in that terminal.
Then choose Claude in T3's provider selector for a new thread. No T3 restart is
required: its provider settings are merged on activation and watched by T3.

On the Mac, run `claude auth login` separately. Claude uses macOS Keychain;
server tokens are not copied to the Mac and Codex/OpenAI tokens cannot log in
to Anthropic. `claude` and T3 on the same host use the same Claude login.

## Updates and Mac delivery

`claude-auto-update.timer` checks the official latest channel daily at 05:00.
It uses the shared Homelab lock and clean-checkout/commit/push/deploy flow.
Both Linux x64 and Darwin ARM64 hashes come from Anthropic's release manifest.
Validation failure restores unchanged candidate pins. A fresh Brick check is
required before release edits; privileged deployment remains broker guarded.

The server publishes a signed Mac Nix output with `just claude-publish-mac`.
The Mac's `claude-update` launch agent checks every 30 minutes and at login.
It verifies the server signature, Apple binary signature and CLI version before
atomically selecting a profile; previous generations remain available. Existing
Claude and T3 processes are not restarted by updates. The native self-updater
is disabled because Nix manages the binary. After an initial Darwin activation,
future binary updates do not require another full Darwin activation.

## MCP compatibility

Homelab tools (`tasks`, `canvas-bridge`) are exposed as plain CLIs rather than
MCP servers. Activation prunes retired Homelab-managed MCP server entries from
`/srv/state/claude/.claude.json` while preserving credentials, preferences,
sessions, and any user-added MCP servers.

OpenAI connected apps, curated Codex plugins, and their OAuth sessions are not
portable Claude MCP definitions. T3 supplies its own orchestration tools to its
provider sessions independently.

Checks: `just check`, Linux system build, `just darwin-eval`, and native CLI
probes. End-to-end model requests require initial Anthropic login.
