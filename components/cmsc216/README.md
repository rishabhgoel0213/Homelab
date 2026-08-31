# CMSC 216 Mac environment

This component produces an isolated `CMSC 216.app` for the managed MacBook.
The app launches a fixed VSCodium build with only clangd, opens the local
`~/Projects/fall-2026/cmsc216` folder as a managed workspace, and exposes
Zaratan tasks backed by the `cmsc216` command. File transfer, remote commands,
testing, formatting, and shells all use that command instead of an
editor-specific SFTP extension.

## Declarative boundary

Nix owns the app, editor and extension versions, workspace, SSH aliases,
Zaratan host keys, course paths, authentication policy, and validation
commands. It does not own UMD passwords, Duo state, GlobalProtect, or mutable
assignment files.

The Zaratan ED25519 key is pinned to the fingerprint published by UMD:

```text
SHA256:Ot4bTjdmv3t8Lwn2uETVlAFPzhFoQafQ7tt+oHAN69w
```

Authentication deliberately uses the UMD password and Duo rather than an SSH
key or GlobalProtect. OpenSSH keeps the authenticated connection alive for up
to eight hours of idle time and reuses it for CLI and VSCodium tasks. No
password or Duo response is stored by this component.

## First deployment

Before deploying, confirm that
`homelab.coursework.cmsc216.directoryId` in `hosts/macbook/default.nix` is the
user's actual UMD Directory ID.

After deployment, launch `CMSC 216.app` and run `CMSC 216: Authenticate with
Duo` from **Terminal: Run Task**. Then run this one-time setup command in the
integrated terminal:

```bash
cmsc216 bootstrap
```

Bootstrap reuses the authenticated connection, creates `~/216-sync`, and runs
the professor's `~profk/bin/cmsc216-setup` command. GlobalProtect remains
separately installed, but this environment neither opens it nor depends on it.

## Normal workflow

The local `~/Projects/fall-2026/cmsc216` directory is canonical and is synced
with the rest of the Fall 2026 project through Syncthing. There is no nested
local `216-sync` directory. Uploads to Zaratan's required `~/216-sync` path
never request remote deletion.

```bash
cmsc216 doctor
cmsc216 auth
cmsc216 auth-status
cmsc216 sync
cmsc216 test
cmsc216 test make test
cmsc216 shell
cmsc216 auth-clear
cmsc216 exam-check
```

`cmsc216 test` uploads local files and runs `make test` in the corresponding
Zaratan directory. Use `cmsc216 run COMMAND...` for assignment-specific test
commands. GDB, Valgrind, assembly, and authoritative compilation should run on
Zaratan rather than on the ARM64 Mac.

`cmsc216 auth` prompts for the UMD password and Duo only when no reusable
OpenSSH connection exists. Sleep, network changes, Zaratan maintenance, or
eight hours of inactivity can end it; run `cmsc216 auth` again when that
happens.

The previous SFTP Neo extension and managed `.vscode/sftp.json` link are
removed during activation. Existing SSH key files and `~/.vscode-sftp` state
are preserved on disk for recovery, but this environment does not use them.

`exam-check` checks only the isolated editor and Zaratan connection. It does
not inspect or close other applications; the student remains responsible for
the complete exam rules.
