# Agent Memory & T3 Chat History

Curated, bloat-resistant user memory shared automatically across every server
agent (Codex, Claude Code, and Antigravity — both inside T3 Code and in the
terminal), paired with a read-only CLI for searching and reading past T3 chats.

## Web dashboard

`https://memory.internal.therealrishabh.com` (tailnet only, loopback port
`8742`).

- **High-Level Overview:** A 2–4 sentence ChatGPT-style summary of what agents
  know about you, editable in place.
- **Categorized Memories:** Atomic facts (`identity`, `preferences`, `ongoing`,
  `workflow`) capped at 60 items. Pin important items to protect them from
  auto-pruning, or set optional `YYYY-MM-DD` expiry dates on temporary context.
- **Recent Changes:** Full audit log with one-click **Undo** for individual
  edits or entire nightly consolidation batches.
- **Agent Prompt:** Exact Markdown currently injected into every agent.
- **Sync from T3 chats:** Triggers an on-demand consolidation pass over new T3
  threads since the last run.

## How all server T3 sessions receive memory automatically

`memory sync` renders `/srv/state/memory/profile.md` and splices a delimited
`<!-- BEGIN USER MEMORY --> ... <!-- END USER MEMORY -->` block into:

- `/srv/state/codex/AGENTS.md` (read by Codex in T3 and terminal)
- `/srv/state/claude/CLAUDE.md` (read by Claude Code in T3 and terminal)
- `/srv/state/antigravity/config/AGENTS.md` (read by terminal `agy` and
  appended dynamically by `components/antigravity/acp-wrapper.py` into every T3
  Antigravity `session/new`, `session/load`, and `session/resume` request)

Every mutation (via CLI, web UI, or nightly consolidator) re-syncs immediately,
and NixOS activation re-applies the block right after refreshing the base
`AGENTS.md` / `CLAUDE.md` files.

## CLI reference

```sh
# Memory
memory show                                     # rendered profile agents see
memory list [--category preferences]            # list saved facts
memory add -c preferences "Prefer concise replies" [--pin] [--expires 2026-12-20]
memory update <id> "Updated text" [--pin|--unpin] [--expires 2026-12-31]
memory forget <id>
memory summary ["New 2-4 sentence overview"]
memory history                                  # audit log
memory revert <event-id|batch-id>               # undo a change or batch
memory consolidate [--dry-run] [--since 7d] [--force]
memory sync                                     # re-render agent instruction files

# Past T3 chats (strictly read-only against /srv/state/t3code/userdata/statev2.sqlite)
t3-history search "tailscale dns" [--project Homelab] [--since 30d] [--active-only]
t3-history list [--project Homelab] [--limit 20]
t3-history read <thread-id-or-prefix> [--offset 0] [--limit 40] [--max-chars 3000]
t3-history projects
```

## Nightly consolidation

`memory-consolidate.timer` runs daily at `03:30 America/New_York`. It prunes
expired unpinned items, reads only T3 threads updated since the previous
watermark, asks `agy --print` (with JSON Schema enforcement in read-only plan
mode) to merge/update/prune durable personal facts and refresh the high-level
overview, auto-applies the batch with full undo logging, and re-syncs all agent
instruction files.

## State and tests

- Database and rendered profile: `/srv/state/memory/memory.db` and
  `/srv/state/memory/profile.md` (mode `0700`, backed up by Backrest).
- Tests: `nix build --no-link .#checks.x86_64-linux.memory` or
  `python3 components/memory/tests/test-memory.py`.
