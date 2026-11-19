# Weekly tasks

A sticky-note to-do board for the week at
`https://tasks.internal.therealrishabh.com` (tailnet only). Weeks run Sunday to
Saturday. The web page, the `tasks` CLI and the `tasks` stdio MCP server all
use one SQLite database, so anything an agent adds appears on the page within a
few seconds.

Python's standard library is the only dependency. The server listens on
`127.0.0.1:8740` and Caddy publishes it on the internal route with ACME HTTPS.

## Web page

- Quick-add box at the top: `fri: call dentist`, `today: groceries`,
  `2026-12-01: submit form`, or plain text for "anytime this week".
- Lanes: "This week" (no fixed day) plus Sunday through Saturday; today's lane
  is outlined.
- Click the circle to finish a task. Click a note to edit its title or notes, or
  to move it to another day or week. Drag notes between lanes on desktop.
- When the previous week still has unfinished tasks, a banner offers to bring
  them into the "This week" lane.
- Tasks added by agents are tinted green with an `agent` badge.
- Keys: `/` add, `[` and `]` change week, `t` this week.

## Agents

Codex and Claude get the MCP server from `components/codex/config/server.toml`.
The tools are:

- `list_tasks(week?, include_done?)`
- `add_tasks(tasks[{title, notes?, day?, week?}], week?)`
- `update_task(task_id, title?, notes?, day?, week?, done?)`
- `delete_task(task_id)`
- `carry_over(from_week?, to_week?)`

A `week` can be `this`, `next`, `last`, `+N`/`-N`, or any `YYYY-MM-DD` date in
that week. A `day` can be `sun`..`sat`, `0`..`6` (Sunday is 0), `today`,
`tomorrow`, a date, or `null` for "anytime".

Pi and shell scripts use the CLI, which records tasks as added by an agent
unless `--source me` is given:

```sh
tasks list                    # this week; `tasks list next`, `--json`
tasks add "mon: gym" "read chapter 4" --week next
tasks done 3fa9c1
tasks move 3fa9c1 thu
tasks carry                   # last week's unfinished tasks into this week
echo '{"tasks":[{"title":"Plan week","day":"sun"}]}' | tasks call add_tasks --arguments -
```

## State and safety

- Database: `/srv/state/tasks/tasks.db` (mode 0700, owned by `rishabh`), which
  Backrest backs up with the rest of `/srv/state`.
- The page has no login; access is limited to the tailnet route. Writes must be
  same-origin JSON requests, so other websites cannot post into the board.
- Tests: `nix build .#checks.x86_64-linux.tasks` or
  `python3 components/tasks/tests/test-tasks.py`.
