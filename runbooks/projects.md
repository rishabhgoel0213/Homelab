# Durable Projects

`projectctl` is the terminal-first control plane for permanent workspaces. Its
canonical root is `/home/rishabh/Projects`; T3 Code can consume the same CLI and
JSON model when its project layer is updated.

## Project Model

Every top-level directory under the project root is discoverable immediately.
An existing directory without metadata is an implicit project. A managed
project adds `project.toml`, which carries:

- a stable UUID, slug, display title, lifecycle status, and creation time;
- conventional paths for source material, notebooks, notes, code, figures, and
  generated artifacts;
- the project-owned Nix flake path;
- the Jupyter kernel command.

The filesystem remains the source of truth. The manifest is portable metadata,
not a database, and native Codex or Pi conversation state remains in each
harness's own runtime store.

## Create or Adopt

```bash
projectctl create linear-algebra
projectctl init existing-research --title "Existing Research"
projectctl list
projectctl list --json
projectctl show linear-algebra --json
```

New projects contain `sources/original`, `sources/processed`, `notebooks`,
`notes`, `src`, `figures`, and `artifacts`, plus a minimal `flake.nix`,
`AGENTS.md`, and `.gitignore`. Initializing an existing directory preserves any
of those files that already exist. When adopting an existing flake, add a
`[jupyter]` kernel command to `project.toml` only after that environment provides
the corresponding kernel runtime.

## Environments and Harnesses

```bash
projectctl env check linear-algebra
projectctl env lock linear-algebra
projectctl shell linear-algebra
projectctl exec linear-algebra -- python -V
projectctl harnesses
projectctl session linear-algebra codex
projectctl session linear-algebra pi
```

Commands run from the project root. When `flake.nix` exists, they enter the
project development shell first. The harness registry is configured in Nix, so
future providers can be added without changing project manifests or the CLI.

## JupyterLab

```bash
projectctl jupyter linear-algebra
projectctl jupyter linear-algebra --json
```

The command prints a direct `/lab/tree/...` URL for the project. For Nix-backed
projects it also installs a project-specific kernelspec under Jupyter runtime
state. The kernel invokes `projectctl`, which resolves the project by UUID and
starts its configured Python kernel inside the same Nix environment.

## T3 Code Boundary

The first pass disables T3 Code's legacy New Task feature. T3's next project
layer should use `projectctl list --json`, `show --json`, and the stable project
UUID rather than inventing another workspace database. T3 may keep its own UI
state and native conversation references, but paths, environment behavior, and
Jupyter links belong to the project control plane.
