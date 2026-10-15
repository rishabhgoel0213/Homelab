# Space wallpapers

The MacBook rotates through 21 curated NASA images: Webb and Hubble nebulae,
interacting galaxies, stellar nurseries, Saturn, and Jupiter. These are telescope
or spacecraft observations rather than illustrations. Infrared observations
use assigned colors. The collection emphasizes interesting subjects across
several years; it does not automatically ingest new releases.

`darwin.nix` installs the Python/Pillow CLI and a built-in macOS JavaScript/AppKit helper, a user LaunchAgent, and a
SwiftBar menu using the existing managed SwiftBar application. The Mac downloads
one image directly from NASA when needed; no server service, credentials, API
key, manual Wallpaper settings, or separate installer is required.

## Behavior

- Rotate hourly while logged into the graphical desktop. Check at login and
  every five minutes, retrying a failed download at the next check. Sleep does
  not accumulate a backlog of wallpaper changes.
- Shuffle all eligible images before repeating; manual **Next image** also
  advances the shuffle. When offline, use cached alternatives and keep the
  existing desktop if none are available.
- Use `~/Pictures/Space Wallpapers` as the bounded cache: eight JPEGs, at most
  8 MiB each. Images retain their proportions and **crop to fill** the entire
  screen by default, without letterboxing or stretching. Each connected display
  receives the image on its current desktop. macOS manages separate Spaces and the lock screen; this does not
  edit their private databases or promise to synchronize inactive Spaces.
- Fetch the verified NASA original or a NASA display rendition. Require at
  least 3840 pixels on the long edge and 2160 on the short edge; never upscale
  downloaded data. In addition, inspect native panel pixels through
  `system_profiler SPDisplaysDataType -json` on the Mac at each rotation. When
  macOS renders a larger backing buffer for display scaling, require that larger
  size too. Never use the logical “looks like” size as the pixel requirement.
- Compute the largest crop at each connected display’s aspect ratio. Reject
  sources if any resulting crop has fewer pixels than that display needs. Apply
  this check before download using catalogue dimensions, to the decoded download,
  to the final JPEG, and to cached/offline candidates. A large total pixel count
  cannot compensate for a crop that is too narrow or too short.
- Downsample toward a 5120-pixel long edge only when doing so preserves enough
  pixels after cropping. Keep more pixels if needed for a tall source or a
  higher-resolution display. Save a high-quality JPEG. Temporary downloads are
  capped at 96 MiB and removed after success or failure, in addition to the
  64 MiB persistent cache.
- The menu shows the current subject and opens NASA's explanation. It also
  offers **Next image**, **Pause rotation**, **Resume hourly rotation**, and the
  image folder. Pausing persists across logins and deployments.
- A new display size or crop policy bypasses the hourly delay at the next tick,
  so deploying this policy replaces the old fit-to-screen wallpaper immediately
  unless rotation is paused. The persisted `displayProfile` and `eligibleImages`
  fields in `space-wallpaper status` show the last applied policy and pool size.

On the inspected Mac, the panel reports 2880 × 1864 native pixels and the current
scaled backing buffer is 3420 × 2214. At those settings, 19 of the 21 catalogue
entries qualify. The narrow Pillars of Creation rendition and the 2160-pixel-high
Jupiter image are excluded. This is a runtime filter: reconnecting displays or
changing scaling recalculates eligibility rather than using a hardcoded model
name or aspect ratio. If display hardware cannot be read reliably, rotation
fails without replacing the desktop instead of falling back to guessed pixels.

Image identities, titles, context, exact URLs, and verified dimensions are in
`catalogue.json`, materialized as `/etc/space-wallpaper/catalogue.json` by Nix.
This deliberately avoids NASA search results that mix low-resolution thumbnails,
diagrams, illustrations, and pictures of people with astronomical observations.
Webb download links were resolved from the full-resolution download sections of
NASA's asset pages. Their display URLs preserve the source aspect ratio (a square
request can unexpectedly return a thumbnail for a wide or tall original).

## Configuration and operation

The workstation profile imports the module and `hosts/macbook/default.nix`
enables `homelab.spaceWallpaper`. The available options are `intervalSeconds`,
`cacheImages`, and `directory`.

Deploy from the server after committing changes and satisfying the existing
clean-checkout guard:

```sh
cd /srv/ops
MACBOOK_DEPLOY_CONFIRM=deploy just darwin-deploy
```

This activates the graphical-session agents through the standard nix-darwin
user-agent activation. If deploying outside an active graphical login, they
start at the next login. SwiftBar shares its existing plugin directory with
Workmode; installation refuses to replace a regular plugin file.

After activation:

```sh
space-wallpaper status
space-wallpaper next
space-wallpaper pause
space-wallpaper resume
space-wallpaper source
space-wallpaper validate
```

State (including the current image's NASA source, description, and cached path)
lives in `~/Library/Application Support/Space Wallpapers/state.json`. Only
`space-<32 hex digits>.jpg` files in the configured image directory are managed
and pruned. Keep manually saved favorites under a different name or outside that
folder. Logs are `/tmp/space-wallpaper.err` and `/tmp/space-wallpaper-menu.err`.
The CLI locks concurrent changes and only records a new current image after
AppKit accepts it. The helper calls AppKit directly through macOS’s built-in
JavaScript bridge; it does not automate System Events or request its permissions.
This avoids a Python/PyObjC libffi trampoline crash observed on this Mac.

Disable with `homelab.spaceWallpaper.enable = false` and redeploy. Existing
images, metadata, and the last selected wallpaper remain. The old SwiftBar
symlink may be removed from its plugin directory after disabling.

## Validation

`just check` includes the component's offline regression tests and catalogue
validation. `just darwin-eval` evaluates its Darwin packages and LaunchAgents.
Testing on Linux does not verify macOS GUI behavior; after the first deployment,
check the wallpaper, the ✦ menu, manual Next, and pause/resume in the graphical
session. Validate source and downloaded pixels when updating the catalogue.

Primary references:

- [NASA Webb gallery](https://science.nasa.gov/mission/webb/multimedia/images/)
- [NASA Hubble gallery](https://science.nasa.gov/mission/hubble/multimedia/hubble-images/)
- [NASA image-library API](https://images.nasa.gov/docs/images.nasa.gov_api_docs.pdf)
- [Apple desktop-image API](https://developer.apple.com/documentation/appkit/nsworkspace/setdesktopimageurl(_:for:options:))
- [Apple crop-to-fill behavior](https://developer.apple.com/documentation/appkit/nsworkspace/desktopimageoptionkey/allowclipping)
