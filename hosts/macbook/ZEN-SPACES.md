# Zen Spaces and layout-only deployment

General, Workbench, and Homelab now use ordinary folders, with no providers or
background refresh. Edit `zen-spaces.nix` for Spaces, folders, and tool/app pins.
Edit `components/projects/categories.json` for project membership; each listed
directory becomes a normal pinned JupyterLab link, ordered as listed. Project
pin IDs stay stable when changing categories. Project metadata is no longer read
automatically: add/remove/move projects explicitly, including new or archived
projects. `project.toml` labels have no effect on this layout. The former live
folders intentionally have new keys to retire their provider state.

## One-command deployment from the server

```sh
just --justfile /srv/ops/Justfile zen-deploy
```

This validates with the Zen compiler, evaluates the current tracked working tree,
uploads over SSH, atomically replaces only `/etc/zen/managed-sidebar.json`, and
verifies its SHA-256 by reading it back. New files must be Git-added for Nix to see
them. Committing reviewed edits is recommended but not required for this command.

The Mac must be reachable over Tailscale, with existing SSH key access and managed
Zen installed. Run from an interactive terminal. SSH is key-based; sudo may ask
for the **Mac login password**. No new passwordless sudo rules are granted. Do not
whitelist arbitrary shell, install, move, or Nix activation commands: that would
grant much more than layout deployment.

There is no Zen rebuild, full Darwin activation, server switch, or automatic
browser restart. After success, save your work, **quit and reopen managed Zen**.
Check that project folders are ordinary folders and links open JupyterLab.
Old live-folder tabs may remain as ordinary tabs because `pinRemoval = "demote"`
preserves browsing state; close duplicates manually after checking them.

This replaces the Nix-generated manifest symlink, not its immutable store target.
A later full Darwin deployment restores the manifest from that deployment's
committed declaration; commit changes to keep both paths consistent. To roll back,
restore the desired declaration and rerun `zen-deploy`. A checksum check does not
verify browser startup reconciliation.

## Retired server feeds

The project-catalog service and route have been removed from the desired server
configuration. If previously deployed, they remain running until your next
reviewed `just switch`. That switch is not needed for the ordinary folders.
