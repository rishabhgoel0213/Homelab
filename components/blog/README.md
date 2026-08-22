# Notebook Blog

The Quarto source lives at `/home/rishabh/Projects/blog`. Public output is
deployed to `/srv/state/blog-site`, while draft previews are deployed to
`/srv/state/blog-site-preview` and served from the internal blog hostname.

## Admin workflow

Open `https://blog.internal.therealrishabh.com/admin/` to create a post, upload
a single notebook, or import an active project known to `projectctl`.

A project import creates a symlink under the blog's `.blog-projects` directory
and records blog-only metadata in `.blog-projects.json`. The project itself is
never modified. Every non-checkpoint `.ipynb` below the linked project appears
as a separate draft. Preview builds stage the project tree once, including
image assets, and render each notebook as its own Quarto post with
`--no-execute`.

Removing a normal post deletes its blog source directory. Removing a
project-backed post unlinks the whole project import and preserves the original
project directory. Both actions rebuild the internal preview.

Publishing is a per-post operation. Select a draft, edit its metadata, and use
**Publish post**; the admin saves that post as published and rebuilds both the
internal preview and public site. A published post instead offers **Update live
post** after source changes and **Move to drafts** to remove it from the public
site. If a publication build fails, a draft is not left marked as published.

**View rendered** always completes an internal draft build before navigating.
The admin HTML, JavaScript, and CSS are served with `Cache-Control: no-store` so
a reload cannot reuse obsolete navigation behavior after deployment.

## CLI operations

From `/srv/ops`:

```console
just blog-list
just blog-new "Post title"
just blog-import-notebook ./analysis.ipynb "Analysis title"
just blog-build
```

`just blog-build` refreshes the internal preview first and then publishes the
non-draft site. Rendering happens in an isolated temporary copy so source
notebooks and linked projects are not rewritten.
