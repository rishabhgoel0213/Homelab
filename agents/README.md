# Agent Cockpit

This is a generated landing directory, not a workspace. Its policy files come
from `/srv/ops/agents`, and its `history` link exposes the small agent-state
index under `/srv/state/agents`.

Choose a canonical target before starting work:

- `cd /srv/ops` for server and agent configuration.
- `cd /home/rishabh/Projects/<project>` for software or research.
- Use an appropriate `/home/rishabh/Documents/<area>` for durable non-code work.
- Run `agent new <short-name>` when the task is genuinely ad hoc and needs files.

Useful inspection commands:

```bash
agent history
agent work
agent gc
```

`agent gc` is a dry run. The scheduled cleanup service uses `--apply` and can
only remove expired directories with a valid `.agent-work.json` manifest.
