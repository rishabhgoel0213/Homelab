# Managed VSCodium presets

This component provides one pinned VSCodium engine with multiple isolated,
declarative presets. Each preset has its own macOS app bundle, user-data root,
settings, and extension directory. Managed presets receive an immutable Nix
extension set; an explicitly mutable preset can instead use a private writable
extension directory.

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
preset = "research"
```

The `therealrishabh.projects` extension exposes **Projects: Open Project** and
uses the same `projectctl` JSON model. It does not maintain another project
database.

Preset isolation separates extension installations, settings, caches, and
editor state. Project compilers and runtimes remain owned by each project's Nix
development shell and are entered through `projectctl`.
