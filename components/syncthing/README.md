# Syncthing Runbook

Syncthing provides a private, Google Drive-like synced folder between this
server and personal devices. The current shared folder is:

```text
/home/rishabh/Documents
```

The service listens for sync traffic on the Tailscale interface and keeps the
web UI bound to localhost on the server.

## Apply Server Config

```bash
cd /srv/ops
just switch
```

Check the service:

```bash
systemctl status syncthing.service
```

## Open The Server UI

From a device on the tailnet, open:

```text
https://sync.internal.therealrishabh.com
```

If internal DNS is unavailable, use an SSH tunnel from the Mac:

```bash
ssh -L 18384:127.0.0.1:8384 rishabh@100.73.159.103
```

Then open:

```text
http://127.0.0.1:18384
```

## Pair The Mac

1. Install Syncthing on macOS.
2. Start Syncthing on the Mac and open its web UI.
3. Copy the Mac device ID into the server UI.
4. Copy the server device ID into the Mac UI.
5. On the server, share `/home/rishabh/Documents` with the Mac device.
6. On the Mac, accept the folder and choose the local Finder location.

Use the explicit device address below if automatic discovery does not find the
server over Tailscale:

```text
tcp://100.73.159.103:22000
```

After pairing, Finder accesses the Mac's local synced folder. Changes sync in
both directions whenever both devices are online.
