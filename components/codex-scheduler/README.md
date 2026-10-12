# Codex scheduler

A local stdio MCP server manages durable jobs. One systemd timer wakes every
minute and runs the oldest queued job with `codex exec`. Python's standard
library is the only application dependency; no HTTP listener or database
server is needed.

## Tools

- `create_job`: save a named job, project, prompt, and schedule.
- `update_job`: edit its configuration, or resume with `enabled=true`.
- `list_jobs` / `get_job`: inspect saved configuration and the next occurrence.
- `pause_job`: disable scheduled runs and cancel queued runs.
- `run_now`: queue a manual run, including for a paused job.
- `get_runs`: inspect statuses, final summaries, log paths, and thread IDs.
- `delete_job`: remove a paused job and its run records; retain log files.

Example `create_job` arguments:

```json
{
  "name": "Weekly homework preparation",
  "project": "/home/rishabh/Projects/fall-2026",
  "prompt": "Check Canvas for newly posted MATH410, PHYS371 and PHYS313 homework. Download instructor PDFs when available; otherwise reuse the established course Typst styles with exact assigned textbook statements. Verify the assignment scope, source edition and rendered PDFs. Preserve existing files. Skip assignments already prepared. Report new files and unresolved source information. Never submit to Canvas.",
  "schedule": {
    "frequency": "weekly",
    "weekdays": [1],
    "time": "09:00",
    "timezone": "America/New_York"
  },
  "enabled": false
}
```

No homework schedule is installed automatically. Verify the desired cadence,
date scope, and semester end date before enabling the example. Weekly days
use ISO numbering: Monday=1 through Sunday=7. Daily schedules omit `weekdays`.
One-time schedules use `{"frequency":"once","run_at":"2026-12-01T09:00:00-05:00"}`.
`end_at` is an optional inclusive timestamp with an explicit timezone offset.
Jobs use the managed model and reasoning effort unless overridden. Timeout
defaults to 30 minutes and may be set from 30 seconds to two hours.

Runs start in fresh Codex sessions using the managed authentication, plugins,
and project instructions. The workspace-write sandbox is restricted to the
chosen directory. The runner explicitly sets `approval_policy="on-request"`
and `approvals_reviewer="auto_review"` so eligible connector and sandbox-boundary
requests are reviewed automatically. Denied requests remain denied; requests
that require human input cannot be answered by an unattended run and must be
reported in its final summary. The per-run timeout also bounds stalled runs.
The scheduler MCP is disabled in child runs to avoid schedules recursively
creating more schedules. Project paths must be
existing directories under `/home/rishabh/Projects`, `/home/rishabh/Documents`,
or `/srv/ops`; symlinks are resolved again at execution.

## Runtime behavior

- Jobs and run records are stored in `/srv/state/codex-scheduler/scheduler.db`.
  The directory is mode 0700 and records/logs are private to `rishabh`.
- Final messages and JSONL logs live in the `runs/` subfolder. Logs are retained
  until explicitly removed; there is no automatic deletion of run artifacts.
- Runs execute serially. `run_now` returns immediately; an existing pending or
  active run for the same job is reused. The next timer tick starts execution,
  after earlier queued work.
- Missed recurrences coalesce into one run; repeated past occurrences are not
  replayed. Expired jobs are disabled. A nonexistent DST wall time is skipped;
  an ambiguous wall time uses its first occurrence.
- Pausing cancels queued work but does not stop active work. Updating a job
  cancels queued work so stale instructions cannot execute. A running job keeps
  its original configuration. Resume with `update_job(enabled=true)`.
- Timeouts kill the child process group. systemd stops the complete service
  control group on shutdown. After an interrupted dispatcher, the next tick
  marks unfinished runs `interrupted` without automatically retrying them.
  Check what the prior run changed before retrying.
- Status `succeeded` means Codex exited successfully and produced a final
  message; inspect that message for the actual task outcome.
- Results are available through `get_runs` and the saved Codex session; they
  are not pushed into an existing interactive chat.

## Operations

The implementation and NixOS units live in `/srv/ops/components/codex-scheduler`.
Registration is in `components/codex/config/server.toml`. Deploy with the normal
`just check` and `just switch` gates. Restart the Codex client when ready to
discover the new tool; deployment does not restart the remote-control service.

```bash
systemctl status codex-scheduler.timer
systemctl list-timers codex-scheduler.timer
journalctl -u codex-scheduler.service
codex-scheduler call list_jobs
codex-scheduler call get_runs
# JSON arguments can be read from stdin to keep prompts out of shell arguments:
codex-scheduler call create_job --arguments - < job.json
```

To stop scheduling globally, stop `codex-scheduler.timer`. Pausing individual
jobs is preferred. Stopping the dispatcher service also interrupts active
work. A manual `sudo systemctl start codex-scheduler.service` processes a tick.
