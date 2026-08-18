# Agent Operating Policy

This is the harness-neutral policy for interactive agents on `nixos-pc`.
`/srv/ops` is the source of truth; the deployed copy is `/etc/agents/AGENTS.md`.

## Start Here

- Read `/etc/agents/ENVIRONMENT.md` before server, NixOS, service,
  network, Codex, backup, or secret work.
- Read `/etc/agents/MEMORY.md` for the small set of deliberately
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
- If work needs its own project, create one with `projectctl create <name>` and
  work in the returned durable directory under `/home/rishabh/Projects`.

Do not create task output, clones, downloads, build trees, or temporary files
directly in `/home/rishabh`. Check whether a canonical checkout already exists
before cloning another copy.

## Work in Projects Deliberately

- Use `projectctl list` to inspect active projects and `projectctl show <name>`
  to resolve a project before writing.
- Use `projectctl session <name> <harness>` to launch Codex, Pi, or another
  configured harness with the project as its working directory.
- Keep original inputs, notes, notebooks, source code, figures, and generated
  artifacts in the project layout instead of creating a second task workspace.
- Never place secrets in Git, agent policy, command arguments, or logs.

## Change Discipline

- Inspect the real target repository and preserve unrelated user changes.
- Use the narrowest relevant checks before applying a system change.
- Keep build outputs out of the checkout: use `just build` for the host or pass
  `--no-link` to direct `nix build` commands so they do not create `result`
  symlinks.
- Use `just switch` only when the user wants the host configuration applied.
- Do not restart Codex or another live service unless the user requests it or a
  restart is unavoidably part of the requested operation.
