# Agent Operating Policy

This is the neutral landing policy for interactive agents on `nixos-pc`.
`/srv/ops` is the source of truth for this file. The generated cockpit at
`/home/rishabh/Agent` is intentionally not a project or a general-purpose
storage directory.

## Start Here

- Read `/home/rishabh/Agent/ENVIRONMENT.md` before server, NixOS, service,
  network, Codex, backup, or secret work.
- Read `/home/rishabh/Agent/MEMORY.md` for the small set of deliberately
  persistent cross-conversation decisions.
- Read the nearest project-local `AGENTS.md` after moving into a project.

## Route Work Before Writing

- Infrastructure configuration, service modules, runbooks, and agent policy
  belong in `/srv/ops`.
- Software projects, forks, and long-lived research repositories belong in
  `/home/rishabh/Projects/<name>`.
- Durable non-code output belongs in the appropriate existing directory under
  `/home/rishabh/Documents`.
- Runtime service data belongs under `/srv/state`; do not edit it as the durable
  source of configuration.
- If a task has no canonical destination, create an isolated expiring directory
  with `agent new <short-name>` and work in the returned path.

Do not create task output, clones, downloads, build trees, or temporary files
directly in `/home/rishabh/Agent` or `/home/rishabh`. Check whether a canonical
checkout already exists before cloning another copy.

## Finish Work Deliberately

- Promote durable output from an agent work directory into its canonical
  project or document location.
- Leave disposable output to expire, or use `agent keep <path>` only when there
  is a concrete reason to retain it.
- Use `agent work` to inspect task storage and `agent gc` for a safe dry run.
  Automatic cleanup deletes only expired directories containing a valid
  `.agent-work.json` manifest.
- Never place secrets in Git, agent policy, conversation indexes, command
  arguments, or logs.

## Change Discipline

- Inspect the real target repository and preserve unrelated user changes.
- Use the narrowest relevant checks before applying a system change.
- Use `just switch` only when the user wants the host configuration applied.
- Do not restart Codex or another live service unless the user requests it or a
  restart is unavoidably part of the requested operation.
