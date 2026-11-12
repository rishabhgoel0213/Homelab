# Hackathon mobile development

Project: `/home/rishabh/Projects/hackathon-mobile` (Expo app in `src/mobile`).
The project owns its pinned npm dependencies, Nix environment, app configuration,
build commands, and native app artifacts. Homelab owns host tooling and services.

## Server

`hackathon-mobile-metro.service` starts Metro at port 8081. It runs with file
watching and Fast Refresh enabled; do not set `CI=1` on this service. The service
only accepts loopback and tailnet peers via systemd IP filtering. Public firewall
ports remain closed. `EXPO_OFFLINE=1` avoids upstream connectivity checks during
startup. The advertised native development URL uses `100.73.159.103:8081`.

Web preview: https://mobile.internal.therealrishabh.com (Tailscale required).
The native app connects directly to Metro over the tailnet. On the server's
Android emulator, use `10.0.2.2:8081` (the emulator's host-loopback bridge).
The existing `t3code.internal.therealrishabh.com` Device panel is independent of
Metro; its video connection does not carry the app's JavaScript bundle.

The separate build SDK in `/etc/mobile-dev/android-sdk` includes Android platform
and build tools through API 37, NDK 27.1.12297006, and CMake 3.22.1/3.30.5. The existing
API 35 virtual device remains suitable for running the app. SDK packages stay
immutable and Nix-managed; native builds and Gradle caches live in the project
and the user's home. Never run sdkmanager updates against the Nix store.

`register-host.py` merges the managed `mobile-mac` entry into T3's watched
settings.json, preserving other settings and device hosts. It saves the initial
file privately before the first edit and makes no change on subsequent identical
runs. No T3 restart is needed. The host may report unavailable until the Mac is
prepared. This setting is intentionally runtime state derived from Nix config.

## Mac: prepared, activated only by explicit deploy

The Darwin module installs Node 24, CocoaPods, Watchman, rsync, mas, and the
version-matched T3 helpers. It links the helpers into T3's **remote** installation
layout (`~/.t3/device/tools/name@version`), moving an existing npm-installed real
directory to a `.before-nix` backup before adopting it. Native Apple helper
signatures must remain intact.

The Mac's packaged hub defaults to iOS-only discovery. T3 starts the Node
entrypoint directly, so an executable wrapper or shell environment variable
cannot apply this setting. A checked packaging substitution sets the CLI default
and includes available iOS simulators without prior usage timestamps. This keeps
a standalone Homebrew `adb` from triggering missing Android SDK commands and
makes the newly created `Hackathon iPhone` selectable before its first boot.
The Linux host's Android discovery is unchanged. T3's capability probe may still
advertise Android on the Mac when `adb` exists; the Mac hub lists only iOS devices.
The packaging check exercises the real hub HTTP endpoint with a fresh simulator
and Android commands that fail if invoked.

After adopting an updated helper package, refresh/reconnect the Mac device host
in T3 so its running hub loads the new store path. Existing helper processes do
not change when their installation symlink changes. Do not restart the T3 chat
service or terminate an unrelated device session.

`MACBOOK_DEPLOY_CONFIRM=deploy just darwin-deploy` activates the configuration,
then runs `mobile-ios-setup` as the logged-in Mac user. Setup:

1. Checks the fresh Brick gate before each command.
2. Gets Xcode (App Store ID 497799835) if `/Applications/Xcode.app` is absent.
3. Selects Xcode, accepts the license, and runs Apple's first-launch installer.
4. Downloads/installs the current iOS runtime via `xcodebuild -downloadPlatform iOS`.
5. Creates an available `Hackathon iPhone` using the runtime's explicit supported
   device list. At the same iOS version, it prefers the general runtime over a
   hardware-specific variant, and selects a recent compatible iPhone. Existing
   simulators are preserved; setup does not start a GUI session.

Privileged actions use `brick-admin run`. The setup does not change sleep settings.
Keep the Mac logged in, awake, on power and connected to Tailscale during testing.
No simulator ports are exposed; T3 uses SSH loopback forwards over Tailscale.

Xcode is an Apple-installed app outside the Nix store, not a reproducible Nix
build input. The App Store account must be signed in. First acquisition may
require an Apple password/Touch ID confirmation on the Mac; neither Nix nor SSH
can guarantee unattended completion of that prompt. After completing the prompt,
rerun `mobile-ios-setup` on the Mac; it preserves completed steps. Do not store
Apple credentials in Git or Nix. Neither `just darwin-eval` nor `just darwin-build`
runs the Apple installer. An iOS Simulator build does not require paid Apple
Developer Program membership; physical iPhone distribution is a separate setup.

## Verification and recovery

Run `python -m unittest discover -s components/mobile-dev -p 'test_*.py'`,
`just check`, and `just darwin-eval` before committing. The project has `just
check`, `just export`, `just android-build`, and an explicit `just ios-build`.
A successful Darwin evaluation/build does not mean Xcode or its runtime has been
installed. If Apple installation fails after activation, retain the activated
Nix configuration and rerun setup after fixing the displayed Apple error.

Use T3 device_list/device_open and the returned agent-device command for device
interaction. Build scripts only build/sync artifacts; use the T3-bound command
to install and open the app. No helper daemon or simulator is globally started by
Darwin activation. Existing sessions stay under T3's control.
