# Workmode

Portable focus profiles with a SwiftBar menu and optional Dock launchers. Abstand
0.1.35 is the initial backend; SwiftBar comes from the locked nixpkgs input.
No server service, network endpoint, account, or custom enforcement daemon is used.

## Configuration

Edit `components/workmode/profiles.json`, validate with `workmode validate`, and
redeploy the Mac. The only configured profile is Study: a locked 90-minute
session blocking reddit.com, x.com, instagram.com, youtube.com, gmail.com, and mail.google.com
(the normal Gmail inbox hostname), including subdomains. There are no app blocks
or automatic app/page launches. Empty blocklists are deliberately disabled.

Each profile has a label, `minutes` (1–1440), `locked`, `blocked_apps` (bundle IDs),
`blocked_sites` (lowercase hostnames, including subdomains), `launch_apps` (bundle
IDs), and `launch_urls` (http/https). Launch lists are optional and run only after
the blocker confirms a session. There is no allowlist, wildcard, URL-path rule,
or shell command field. Unknown configuration keys fail validation.

Find an application's bundle ID with:

```sh
/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' /Applications/Example.app/Contents/Info.plist
```

## After Mac deployment

The user LaunchAgent installs the plugin in SwiftBar's existing plugin folder,
or selects `~/Library/Application Support/Workmode/SwiftBar` on first use. It
opens SwiftBar and sets up Abstand's own recovery agent. Existing SwiftBar plugins
are preserved; an existing regular file named `workmode.15s.sh` is not overwritten.

1. Complete Abstand's onboarding and grant its Accessibility permission in
   System Settings. These macOS permissions cannot be silently provisioned here.
2. Run `workmode setup` if onboarding prevented the login setup from completing.
3. Run `workmode doctor` to check the live CLI and recovery agent.
4. Test a short session using one harmless app/site, including Zen navigation,
   private browsing, sleep/wake, and restarting Abstand. `doctor` cannot prove
   Accessibility or website enforcement works; an active session is not proof
   that a particular browser is blocked.
5. Check that a locked session refuses early stop and naturally expires. Only
   after that test use longer sessions.

SwiftBar refreshes every 15 seconds and when opened. It displays the remaining
minutes and a lock, offers profile starts while idle, and allows early stopping
only for unlocked managed sessions. Backend failure is shown as unknown/error,
never as idle. Profile launcher bundles are under `/Applications/Nix Apps` and
can be dragged to the Dock; the menu already provides one-click starts.

Commands: `workmode list`, `validate`, `setup`, `doctor`, `start study`, `status`,
`stop`, `open`, and `menu`. Status prints JSON. The same interface is usable from
Apple Shortcuts or a keyboard shortcut. Login errors are in
`/tmp/workmode-login.err`.

## Backend boundary and locking

Only the Abstand adapter knows its CLI and JSON formats. It verifies the exact
version and checks saved restrictions, enforcement mode, and duration before
starting. Repeated profiles reuse a matching saved Intention; changed profiles
create a new version. Old Intentions are retained to preserve session history.
The controller does not change or delete unrelated Intentions.

Strict sessions use Abstand's strict enforcement and require its recovery agent.
The wrapper does not implement an easily bypassed countdown lock. It serializes
mutating commands, rejects overlapping sessions (including sessions made in
Abstand directly), and reconciles uncertain mutation responses. The countdown
uses the backend start timestamp and only declares completion when the backend
does. Closing SwiftBar does not end a session.

These are self-control restrictions in the user's session, not an OS security
boundary against an administrator. Reliability in Zen and on the target macOS
must be established by the deployment smoke test.

## Replacing Abstand

Profiles, menu actions, and launcher names do not depend on Abstand. Add an
adapter to `BACKENDS` implementing ready/setup, sessions, recovery checks,
prepare/start/stop and opening the app, and select it using `backend` in JSON.
Unsupported backends and settings are rejected. The persisted backend marker
requires the old backend to confirm no active session before switching.

A Focus 2 adapter is NOT included: its profile provisioning and live-session
verification need validation against an installed licensed copy. Its documented
URL API offers the required blocklist/timed-lock primitives, but pretending to
have verified equivalent enforcement without that test would be misleading.
Changing to Focus should require an adapter and package change, not rewriting
profiles, the menu, or launchers. Finish sessions before replacing/upgrading
backend apps; never remove a running locked backend as part of migration.

## Validation / deployment boundary

`python3 components/workmode/test_workmode.py` tests configuration rejection,
strict intent creation, changed settings, uncertain responses, overlap guards,
countdown and menu behavior, and backend migration guards. The flake check runs
these tests and validates the checked-in profiles. `just darwin-eval` validates
the host integration. Building an Apple-silicon app bundle on the Mac and the
permission/browser smoke test are separate from Linux checks.

Upstream contracts used:
- https://github.com/builder-group/abstand/blob/v0.1.35/apps/desktop/src-tauri/src/cli/README.md
- https://github.com/builder-group/abstand/blob/v0.1.35/apps/desktop/src-tauri/src/modules/recovery_agent/README.md
- https://github.com/swiftbar/SwiftBar/blob/v2.0.1/README.md
