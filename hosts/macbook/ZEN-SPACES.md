# First-pass Spaces

`zen-spaces.nix` declares Workbench and Homelab; `default.nix` retains General.
Workbench has Research, Coursework, Development, Writing, Uncategorized, and
Tools & Pages. Homelab has Everyday Apps and Administration.
Folder/pin keys are stable identities: change display names without renaming keys.

## Project categories

The private `project-catalog` service reads the live projectctl inventory on each
request. Initial assignments live in `components/projects/categories.json`.
An existing project's `project.toml` can override its initial assignment:

```toml
[organization]
category = "research"
labels = ["physics", "lhcb"]
```

Supported categories are research, coursework, development, writing, and
uncategorized. Labels are optional descriptive metadata, not folder selectors.
Unknown or missing categories fall back to Uncategorized (unless an initial
assignment exists). Archived projects are omitted. No project files are modified
by the service. Invalid manifests return a failed request rather than an empty
feed, so Zen retains its last successful list.

Each entry opens that project's JupyterLab directory; there are no per-project
notebook folders. Feeds refresh every five minutes while Zen is running and online.
Manifest changes need no deployment. Changes to the initial assignment map require
a server deployment; changes to the declared folder layout require a Mac deployment.

## Deploy and test

From `/srv/ops`, commit the reviewed changes (the Mac workflow uses committed
source), then deploy the server feed before the Mac declaration:

```sh
just check
just switch
MACBOOK_DEPLOY_CONFIRM=deploy just darwin-deploy
```

The server activation also applies any other pending host configuration changes;
review those before switching. No Zen source rebuild is needed for these changes.

On the Mac, connect to Tailscale, verify
`https://projects.internal.therealrishabh.com/feeds/research.xml` loads, then
restart the managed Zen browser. Check all three Spaces, the five project folders,
and static tools/app links. Change one project's category and refresh the folder
(or wait five minutes) to test movement. Restore the category after testing.

## Native RSS limitations

This first pass uses Zen's existing RSS provider, not a custom catalog provider.
When a project disappears from a category, Zen can **close its live-folder tab**.
Open notebook work in a separate ordinary tab before changing categories or
archiving projects. Existing entry title/URL changes may not update until the
entry is recreated; manually dismissed entries may stay dismissed. Stable feed
GUIDs prevent routine refreshes from duplicating entries, but moving between
folders is not an in-place tab move. Automatic preservation of active project
tabs is a follow-up browser feature, not part of this declaration.

The catalog is private through the existing internal ingress, not a public feed.
It exposes project titles and Jupyter links to authorized private-network clients.
No undeclared sensor dashboard URL or personal credentials are included.
