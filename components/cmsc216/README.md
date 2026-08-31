# CMSC 216 Mac environment

This component produces an isolated `CMSC 216.app` for the managed MacBook.
The app launches a fixed VSCodium build with only clangd and SFTP Neo, opens
the local `216-sync` workspace, and exposes Zaratan tasks backed by the
`cmsc216` command.

## Declarative boundary

Nix owns the app, editor and extension versions, workspace, SFTP settings,
SSH aliases, Zaratan host keys, course paths, and validation commands. It does
not own UMD passwords, Duo state, the device's SSH private key, GlobalProtect,
or mutable assignment files.

The Zaratan ED25519 key is pinned to the fingerprint published by UMD:

```text
SHA256:Ot4bTjdmv3t8Lwn2uETVlAFPzhFoQafQ7tt+oHAN69w
```

The Mac-local private key is created interactively by `cmsc216 bootstrap`, is
protected by the macOS Keychain, and never enters Git or the Nix store.

## First deployment

Before deploying, confirm that
`homelab.coursework.cmsc216.directoryId` in `hosts/macbook/default.nix` is the
user's actual UMD Directory ID.

After deployment, launch `CMSC 216.app` and run the `CMSC 216: Doctor` task.
Then run this once in the integrated terminal:

```bash
cmsc216 bootstrap
```

Bootstrap creates the device-local SSH key, prompts for the initial Zaratan
authentication, adds only the public key to `authorized_keys`, creates
`~/216-sync`, and runs the professor's `~profk/bin/cmsc216-setup` command.

GlobalProtect remains separately installed. Before an SFTP upload, sync, test,
or shell command, a failed noninteractive SSH probe opens GlobalProtect in the
background. Interactive SSH/Duo remains available if the tunnel is not active.

## Normal workflow

The local directory is canonical. Uploads never request remote deletion.

```bash
cmsc216 doctor
cmsc216 sync
cmsc216 test
cmsc216 test make test
cmsc216 shell
cmsc216 exam-check
```

`cmsc216 test` uploads local files and runs `make test` in the corresponding
Zaratan directory. Use `cmsc216 run COMMAND...` for assignment-specific test
commands. GDB, Valgrind, assembly, and authoritative compilation should run on
Zaratan rather than on the ARM64 Mac.

`exam-check` checks only the isolated editor and Zaratan connection. It does
not inspect or close other applications; the student remains responsible for
the complete exam rules.
