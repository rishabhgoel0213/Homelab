# Agent Project Entry Point

The deployed policy files in `/etc/agents` come from `/srv/ops/agents`.

Choose a canonical target before starting work:

- `cd /srv/ops` for server and agent configuration.
- `cd /home/rishabh/Projects/<project>` for software or research.
- Use an appropriate `/home/rishabh/Documents/<area>` for durable non-code work.
- Run `projectctl create <name>` when work needs a new durable project.

Useful inspection commands:

```bash
projectctl list
projectctl show <name>
projectctl session <name> codex
projectctl jupyter <name>
```
