# On-demand Xcode & iOS Simulator cache (`apple-dev`)

Keeps `Xcode.app` and the matched iOS Simulator runtime archived on `nixos-pc`
under `/var/cache/apple-dev` (outside Backrest's `/srv/state` backups) so the
MacBook can stay clean day-to-day (~23 GB freed) and restore them over local
LAN/Tailscale in a few minutes without re-downloading from Apple.

Xcode Command Line Tools (`/Library/Developer/CommandLineTools`) stay installed
permanently on the MacBook so `git`, Nix, and Homebrew always work.

## Cache layout on `nixos-pc`

```text
/var/cache/apple-dev/
├── manifest.json
├── xcode/Xcode-<version>-<build>.cpio.zst      # ditto CPIO stream + zstd
└── runtimes/iOS-<version>-<build>/Restore/     # Cryptex .dmg + manifests + Firmware/
```

- `Xcode.app` is streamed through macOS `ditto -c --keepParent` + `zstd` so
  Apple code signatures, symlinks, xattrs, and bundle permissions remain intact
  without needing extra temporary disk space on the MacBook.
- Only the single iOS runtime matched by `xcrun simctl runtime match list` is
  cached by default (override with `--runtime-id <uuid>`). The Cryptex `.dmg`
  is already LZFSE-compressed so it is stored raw with SHA-256 verification.

## Usage

### Archive current Mac Xcode + iOS runtime to `nixos-pc`
From `nixos-pc` (works even before Mac Darwin activation):
```bash
just apple-dev-archive
just apple-dev-verify
just apple-dev-status
```
Or from the MacBook:
```bash
apple-dev archive
apple-dev verify
```

### Free ~23 GB on the MacBook
Run on the MacBook (requires unbricked phone / `brick-admin` when enrolled):
```bash
apple-dev purge
```
`purge` refuses to run unless the currently installed Xcode and matched iOS
runtime are already recorded in `nixos-pc`'s `manifest.json` (pass `--force` to
override) and `/Library/Developer/CommandLineTools` is present.

### Restore on demand on the MacBook
```bash
apple-dev hydrate
```
Streams `Xcode.app` from `nixos-pc` while verifying its SHA-256 before moving
it into `/Applications/Xcode.app`, runs `xcode-select` and
`xcodebuild -runFirstLaunch`, registers the verified iOS runtime via
`xcrun simctl runtime add --move`, and creates a default `iPhone` simulator.
