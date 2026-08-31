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
- the Jupyter kernel command;
- optional Syncthing targets under `[sync]`.

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

New project flakes expose the same development shell on `x86_64-linux` and
`aarch64-darwin`. Existing projects remain valid, but must add a Darwin output
before their Nix environment can be entered on the Mac.

## Project Sync

Project synchronization is opt-in and declarative. The project manifest records
desired targets while each project gets an independent Syncthing folder. Server
and Mac paths remain conventional and do not need to match:

```text
/home/rishabh/Projects/<name>
/Users/rishabhgoel/Projects/<name>
```

Declare or remove desired state without contacting the target:

```bash
projectctl sync enable linear-algebra --target macbook
projectctl sync disable linear-algebra --target macbook
projectctl sync status linear-algebra
```

Apply every declaration for the Mac as one explicit deployment:

```bash
projectctl sync deploy macbook
```

Deployment first reconciles the Mac, then the server. It refuses to merge into
an unrelated non-empty destination. Removing a relationship deletes only the
Syncthing folder configuration; files remain on both devices. A server-only
recovery reconciliation is available as `projectctl sync reconcile`.

Folder IDs are derived from the stable project UUID, so renaming a display title
does not create another share. Reconciliation owns only folder IDs beginning
with `project-`; manually managed Documents, Photos, and device folders are not
modified. Every managed project folder is bidirectional, uses staggered
versioning, and receives local `.stignore` defaults for Git metadata, Nix build
outputs, editor caches, notebook caches, and CMSC 216 transfer backups.

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
