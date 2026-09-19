# Managed VSCodium presets

This component provides one pinned VSCodium engine with three isolated,
declarative applications: `VSCodium Remote`, `VSCodium Local`, and
`VSCodium 216`.
Each preset has its own macOS app bundle, user-data root, settings, and extension
directory. The remote application receives the complete Nix-managed extension
set, the local application receives the same development baseline inside
Scratch's private writable extension area, and the course application keeps its
smaller course-specific set.

The three application variants use their corresponding checked-in ICNS assets
from `icons/`: Remote for `VSCodium Remote`, Local for `VSCodium Local`, and
CMSC216 for `VSCodium 216`. Updating an icon should also increment that preset's
`appVersion` so macOS refreshes Launch Services and Dock icon caches.

Preset settings are installed as user-writable regular files rather than links
to the immutable Nix store. This lets VSCodium persist its own harmless settings
rewrites without permission errors; the declared settings baseline is restored
whenever the Mac configuration is deployed.

Extension bundles are composed in the Mac host configuration. The generated
launcher commands are:

```sh
vscodium-env list
vscodium-env open general /Users/rishabhgoel/Projects/example
codium-general --list-extensions
```

`projectctl ide PROJECT` resolves a local project and launches its configured
preset. Managed projects can set a default in `project.toml`:

```toml
[editor]
preset = "local"
```

The `therealrishabh.projects` extension exposes **Projects: Open Project** and
uses the same `projectctl` JSON model. It does not maintain another project
database. In the remote application it runs beside the remote extension host,
lists the server's canonical projects, and opens the selected project through
the current SSH authority.

Launching `VSCodium Remote.app` connects to `nixos-pc` and opens
`/home/rishabh/Projects`. `VSCodium Local.app` opens a normal local window and
retains the former Scratch preset's user-data root. The server-side copies of
the managed workspace extensions are reconciled into
`~/.vscodium-server/extensions` by the NixOS activation. The client connection
is provided by the pinned `jeanp413.open-remote-ssh` extension from Open VSX.
The Jupyter extension's writable temporary directory is scoped to each preset
instead of linking the extension into the system-wide `/tmp` tree.

Preset isolation separates extension installations, settings, caches, and
editor state. Project compilers and runtimes remain owned by each project's Nix
development shell and are entered through `projectctl`.
