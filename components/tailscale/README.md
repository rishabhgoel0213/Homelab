# Tailscale Runbook

## Control Model

Tailscale node state is controlled with the normal `tailscale` CLI. Tailnet
admin state is controlled with `tsctl`, which uses encrypted OAuth client
credentials from `sops`.

## OAuth Client

Tailscale does not provide a user-login authorization flow for arbitrary local
automation. Create a tailnet-owned OAuth client in the admin console:

```text
https://login.tailscale.com/admin/settings/oauth
```

For internal DNS automation, grant:

```text
DNS: Read
DNS: Write
```

`tsctl` requests those scopes separately because Tailscale grants DNS write as
the `dns` token scope when `dns:write` is requested by itself.

For broader Codex-driven tailnet administration, add the other scopes you want
Codex to manage. Prefer starting narrow and expanding deliberately.

Tailscale shows the OAuth client secret once. Store it immediately in Apple
Passwords/Vaultwarden, then run:

```bash
cd /srv/ops
just tailscale-store-oauth
```

Verify:

```bash
just tailscale-verify
just tailscale-dns
```

Apply or repair split DNS for private homelab apps:

```bash
just tailscale-apply-internal-dns
just tailscale-split-dns
```

## Current Internal DNS Target

The server's Tailscale IPv4 is:

```text
100.73.159.103
```

The intended split DNS route is:

```text
internal.therealrishabh.com -> 100.73.159.103
```
