# T3 Code nightly

The server runs the official, unmodified upstream nightly at:

https://t3code.internal.therealrishabh.com

The Nix package downloads the versioned Linux x64 release from
[pingdotgg/t3code](https://github.com/pingdotgg/t3code/releases) and verifies its
pinned SHA256. It does not build or execute the private fork.

## Updates

`just t3code-update` resolves npm's official `t3@nightly` tag, updates the
version and hash in `package.nix`, and builds the host without activating it.
It also resolves and hashes the official Android APK attached to that exact
release. Both pins advance together; a release without exactly one matching APK
is rejected. A failed build restores both old pins. An exact nightly version can be supplied
as an argument.

`just t3code-auto-update` runs in `/home/rishabh/Projects/Homelab`, commits both
pins, pushes origin/main, fast-forwards `/srv/ops`, and deploys that same commit
through the shared `tools/deploy` workflow. It checks the service and matching
APK endpoint. Updates defer during uncommitted work; failed publications and
deployments remain eligible for retry. The systemd timer runs daily at 06:00 America/New_York with
up to ten minutes of randomized delay. It shares the Codex/Pi deployment lock.
Updates restart T3 Code and can interrupt active T3 turns or terminals.

## State and providers

State remains at `/srv/state/t3code`. `CODEX_HOME=/srv/state/codex` shares the
managed Codex authentication. Provider configuration otherwise uses upstream
defaults and the normal upstream Settings UI.

The custom projectctl adapter, Pi provider, task UI, Jupyter editor integration,
and private Android/Expo update service are removed from the deployment.
Use upstream mobile clients. Add project paths in the standard T3 UI; projectctl
continues independently. The old fork checkout is retained for recovery but is
not a package input. Initial migration backups are under
`/srv/state/t3code-backups`.

The initial fork conversion uses `bin/migrate-private-fork.py` with the service
stopped. First provision the backup parent with
`sudo install -d -m 0700 -o rishabh -g users /srv/state/t3code-backups`.
It backs up the entire state, resets fork settings/keybindings, and
reconciles conflicting migration IDs 36, 41, and 42. Upstream then performs its
own schema migration into `userdata/statev2.sqlite`. This is a one-time step,
not part of the nightly updater. To recover the old fork, stop T3 and restore
the full backup together with the prior NixOS generation.

## Operations

```bash
just t3code-doctor
just t3code-pair
just t3code-status
just t3code-logs
systemctl status t3code-auto-update.timer
journalctl -u t3code-auto-update
```

The server binds to loopback port 3773; Caddy provides the existing private HTTPS
route. Pairing is handled by upstream T3. The route remains tailnet-only.

## Official nightly Android download

Open https://updates.internal.therealrishabh.com/ on the phone with Tailscale
enabled, then download and install the APK. The stable download URL is
`/nightly.apk`; `/bootstrap.apk` remains an alias for the old bookmarked URL.
`/release.json` identifies the server nightly, original upstream APK filename,
and pinned hash. Caddy serves the verified APK directly from the Nix store and
rejects connections outside the tailnet. Responses disable caching so a phone
does not reuse yesterday's APK. The old custom `/api/manifest` Expo endpoint is
not restored.

Every successful daily nightly deployment switches the server and this download
to the same upstream release. The file is the official, unmodified APK, not a
locally rebuilt fork. Android still requires confirmation to install new APKs;
this endpoint does not push or silently install them. The official app's own
compatible JavaScript updates come from upstream's Expo service and follow
upstream's mobile update channel independently of the server pin. Native changes
require downloading and installing a new APK. A signature mismatch with an old
custom build may require uninstalling that phone app first; save any local drafts
before uninstalling. Server conversations and project files stay on the server.

Deployments preserve the running T3 Code service and its active sessions.
As with Codex remote control, `restartIfChanged = false` defers package and
service changes until a manual `brick-admin run systemctl restart t3code.service` or a
reboot. Restart manually when sessions can safely be interrupted. Automatic
recovery after a process failure remains enabled.

## Linux web and device dependencies

The service provides nix-ld libraries for upstream's version-matched downloaded
Chrome headless shell, keeping its sandbox enabled. PDF preview is supplied by
upstream's client; Poppler utilities are also available for PDF processing.
FFmpeg (including H.264), Node.js, Java, adb, and an Android SDK with API 35,
build tools, emulator and x86_64 Google APIs image support Android workflows.
Android SDK licenses are accepted declaratively. No iOS tooling is installed.
The SDK is exposed through ANDROID_HOME and Java through JAVA_HOME.
The SDK also provides `cmdline-tools/latest` as an alias to Nix's versioned
command-line tools. T3 probes that exact path; without the alias it incorrectly
reports the installed tools as an older, unsupported SDK.
After deployment, finish active turns and run
`brick-admin run systemctl restart t3code.service` to pick up the new service
environment (with the phone unbricked).

### Android virtual device

The server user's `t3code_pixel_9_api35` AVD uses the Pixel 9 profile and the
packaged Android 15 / API 35 Google APIs x86_64 image. AVD data lives in the
standard `~/.android/avd` directory, separately from the immutable SDK. The
`t3code-android-avd` oneshot service creates it if absent and preserves existing
data. T3 starts emulators headlessly with SwiftShader software graphics.
The equivalent manual provisioning commands (as `rishabh`) are:

```bash
printf 'no\n' | avdmanager create avd --name t3code_pixel_9_api35 \
  --package 'system-images;android-35;google_apis;x86_64' --device pixel_9
emulator -accel-check
emulator -list-avds
```

Nix's `latest` alias can produce a harmless duplicate-package warning from
avdmanager. SDK packages remain managed through Nix, not sdkmanager updates.
For a headless boot check, use `emulator @t3code_pixel_9_api35 -no-window
-no-audio -no-snapshot -gpu swiftshader`; check `sys.boot_completed` with adb,
then shut down the test instance before opening the device in T3.

The `device-tools` Nix package supplies locked `agent-device` and
`expo-device-hub` dependencies, including the patched native WebRTC module.
Tmpfiles links them into T3’s versioned tool directories with its completion
markers; no runtime npm install is needed. The build checks that their versions
match the pinned T3 binary. When a future nightly changes those versions, update
`device-tools/package.json`, regenerate its npm lockfile, and update
`npmDepsHash` alongside the nightly pin; the build rejects mismatched helpers.

In T3 Settings → Integrations → Devices, enable the local Android host. Agent device access
is a separate setting that takes effect in a new agent session. The existing
private T3 HTTPS route carries the device panel; do not expose adb publicly.
