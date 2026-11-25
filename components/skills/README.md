# Global Cross-Harness Agent Skills

Manages global agent skills (`<name>/SKILL.md`) across **Codex**, **Claude Code**,
and **Antigravity** (both terminal CLIs and T3 Code sessions) on `nixos-pc`.

## Architecture

Hybrid two-layer store:

1. **Declarative skills** (`components/skills/declarative.nix`): pinned via Nix
   (`pkgs.fetchFromGitHub` or local `./builtin/<name>`), validated at build time,
   and synced automatically on NixOS activation.
2. **Mutable installed skills** (`/srv/state/skills/installed/<name>`): installed
   on the fly with `skills add` without needing a commit, `just deploy`, or
   unbricking. Metadata (source URL, subpath, branch/ref, and commit SHA) is
   recorded in `/srv/state/skills/manifest.json`.

Active skills (`declarative` overlaid by `installed`) are materialized atomically
into each harness's native user skill directory:

- **Codex:** `/srv/state/codex/skills/<name>` (leaves `.system/` untouched)
- **Claude Code:** `/srv/state/claude/skills/<name>` (leaves `synced/` untouched)
- **Antigravity:** `/srv/state/antigravity/config/skills/<name>` (read by
  terminal `agy` via `~/.gemini` and automatically symlinked by T3 Code into its
  isolated Antigravity provider profile)

Managed entries are tracked by content digest in `/srv/state/skills/managed.json`,
so unmanaged harness directories (`.system/`, `synced/`, or manual skills) are
never overwritten or deleted.

## CLI Usage

```bash
# List active skills and per-harness sync status
skills list

# Show details for one skill
skills show socratic-tutor

# Quickly try a skill from GitHub, a git URL, or a local directory
skills add github:owner/repo/path/to/skill
skills add https://github.com/owner/repo/tree/main/skills/my-skill
skills add owner/repo --skill my-skill
skills add owner/repo --all
skills add ./my-local-skill

# Update git-installed skill(s)
skills update
skills update my-skill

# Promote a tried skill to declarative.nix (computes SRI hash automatically)
skills promote my-skill
# Add the snippet to components/skills/declarative.nix, commit, `just deploy`, then:
skills remove my-skill

# Reconcile harness copies or verify health
skills sync
skills doctor
```

## T3 Code Refresh Note

New T3 Code threads pick up newly synced skills immediately. Existing threads can
reload them via T3 Code's **Restart agent session** action.
