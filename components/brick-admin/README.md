# Brick administrative guard

The root-owned `brick-admin` broker permits administrative commands when the
phone reports fresh unbricked state. Once enrolled, a bricked, stale, unknown,
or unreachable phone requires the device's paper recovery secret for each
invocation. There is no cached Brick override. Native sudo authentication still
applies (password on the Mac; the server retains its existing passwordless policy).

## Enrollment and daily use

Deployment installs the broker without enrolling it. **Until enrollment, the
existing sudo policy remains unrestricted.** On each machine, in your own
interactive terminal (use `ssh -t` for a remote terminal):

```
brick-admin status
brick-admin enroll
```

Unbrick your phone first. Enrollment displays a random 256-bit secret once,
directly on `/dev/tty`, and asks you to retype it with echo disabled. Write it on
paper and label it with the machine name. Nothing should generate or capture
this secret through an agent, terminal recording, chat, or redirected output.
Only the SHA-256 verifier is saved, with root-only permissions. Confirmation and
a second fresh-unbrick check precede replacement of the verifier.

After enrollment:

```
brick-admin run nixos-rebuild switch --flake /srv/ops#nixos-pc
brick-admin run systemctl restart some-service
brick-admin run docker ps
brick-admin rotate
```

Direct sudo is restricted to the fixed `/etc/brick-admin-root` broker. Cached
sudo credentials do not bypass its check. The deployment recipes use
`tools/admin`, which selects the broker after enrollment and retains the original sudo
path during bootstrap. A direct sudo call from an older
script will be denied after enrollment; use `brick-admin run` instead.

Each machine has an independent recovery secret for offline recovery. `rotate`
requires a fresh unbricked phone, even with a valid recovery secret. It can be
used repeatedly; the old verifier is replaced. A secret does not authorize
rotation through the rotation command while bricked. An authorized root shell
can of course change the guard itself, as it can any other system configuration.

## Other privilege paths

The server's root-Docker socket is root-only; use the broker for Docker admin
operations. Existing containers continue running. After enrollment, polkit
requests from the normal account are denied while bricked or disconnected.
Root SSH login is already disabled and the server root password is locked.
Nix trusts only root on both machines.

Mac enrollment removes the normal account from the `admin` group, closing the
GUI administrator route. This is permanent until explicitly changed through an
authorized admin command; use the broker for administrative work even while
unbricked. The Mac's ordinary account password continues to authenticate its
explicit sudo rule. No protected macOS PAM file is modified.

Ordinary project reading, writing, execution, user profiles and Nix builds remain
available. Docker access to the *root* daemon is administrative access, not an
unprivileged project operation. Existing root processes, prior privileged
connections/authorizations, deliberate privileged changes before bricking, and
physical/Recovery-mode access are outside this guard's boundary.

## State, failure behavior, and recovery

The broker uses a dedicated relay on tailnet port 1022. Unlike the ordinary
Workmode listener, this is a privileged port: an ordinary server user cannot
impersonate it during restarts. Responses must explicitly say unbricked, with a
matching latch and an age no greater than three seconds. Network and phone
sampling latency still applies. Proxy settings and redirects are ignored/refused.

Root-only state is `/var/lib/brick-admin` on Linux and `/var/db/brick-admin` on
macOS. The sudoers restriction is included last from `sudoers.d/policy` in that
directory. `/etc/brick-admin.enrolled` is a public, root-owned enrollment marker
used by the polkit guard. The verifier is separate and private. A stable managed
broker path allows future Nix generations to replace the implementation without
leaving sudoers pinned to an obsolete store path.

If phone connectivity fails, use the paper secret with `brick-admin run ...` to
repair it. Do not delete the verifier as a troubleshooting shortcut. To undo the
policy intentionally, use an authorized root command to remove the restriction
and enrollment marker, and restore Mac admin membership if desired, then update
Nix configuration. Keep an already-authorized root session during initial
manual enrollment testing; existing sessions are explicitly outside the guard.

The secret is not written to disk by this program and is not sent over the
network. Its mutable random buffer is wiped and references are dropped. Python
and terminal software cannot guarantee erasure of every immutable memory copy,
swap page, terminal scrollback, screenshot, or external recording. Disabling
core dumps and using a terminal rather than stdout reduce accidental retention;
they do not provide that impossible guarantee.

## Validation

`test_policy.py` and `test_gate.py` cover freshness, malformed observations,
verifier rotation, confirmation races, and persistence. They run in `just check`
and have also been run on macOS. `test_installed.py` exercises the packaged helper
with a real pseudo-terminal, a test-only verifier, and network failure. Run it
only with `sudo unshare --mount --net --fork python3 .../test_installed.py`;
it refuses the host namespaces. It verifies successful recovery, rejection of
an incorrect secret, rejection of offline rotation, and absence of key echo.
No real enrollment secret is generated by these tests.
