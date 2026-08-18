# Durable Projects

`projectctl` is the terminal-first control plane for permanent workspaces. Its
canonical root is `/home/rishabh/Projects`; T3 Code consumes the same versioned
JSON model through its server-side project-control adapter.

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
projectctl capabilities --json
projectctl rename linear-algebra "Linear Algebra II"
projectctl archive linear-algebra
projectctl unarchive linear-algebra
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
projectctl exec --cwd /home/rishabh/Projects/linear-algebra/src linear-algebra -- python -V
projectctl exec --clean-stdout linear-algebra -- some-jsonl-provider
projectctl harnesses
projectctl session linear-algebra codex
projectctl session linear-algebra pi
```

Commands run from the project root, or from a validated child directory supplied
with `--cwd`. When `flake.nix` exists, they enter the project development shell
first. The harness registry is configured in Nix, so future providers can be
added without changing project manifests or the CLI.

Use `--clean-stdout` for commands whose stdout is a machine protocol. Nix and
development-shell startup output is sent to stderr, then the original stdout is
restored immediately before the command starts. The command's own stdout and
stderr remain distinct.

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

T3's server invokes `projectctl` for catalog, lifecycle, environment, and
Jupyter operations, then reconciles active entries into its conversation
projection using the stable project UUID. The web and Android clients use that
RPC surface; neither client reads the filesystem directly.

T3 keeps UI state and native conversation references. Project identity, paths,
environment behavior, lifecycle status, and Jupyter links belong to the project
control plane. Codex and Pi child processes are routed through `projectctl exec`
inside the canonical project tree, while legacy projects outside that tree keep
their host execution behavior.
