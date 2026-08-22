# Cloudflare Runbook

## Control Model

Cloudflare is controlled from this server with:

- `cfctl` for API calls and common operations.
- `cloudflared` for tunnel login and tunnel management.
- `wrangler` for Workers, Pages, and developer resources.

## Admin Token

Create a Cloudflare API token in the dashboard:

```text
https://dash.cloudflare.com/profile/api-tokens
```

For broad command-line control, create a custom token with:

```text
Account resources: your Cloudflare account
Zone resources: therealrishabh.com
Permissions: Edit for the account/zone features you want Codex to manage,
             Read where Edit is not available.
```

For this server, the practical minimum is:

```text
Zone: DNS: Edit
Zone: Zone: Read
Zone: SSL and Certificates: Edit
Zone: Zone Settings: Edit
Account: Cloudflare Tunnel: Edit
Account: Workers Scripts: Edit
Account: Workers Routes: Edit
Account: Pages: Edit
```

If you truly want near-admin command-line control, add the remaining relevant
Account and Zone permissions with `Edit` where available. Prefer an API token
over the legacy Global API Key.

Cloudflare only shows the token secret once. Store it immediately in Apple
Passwords/Vaultwarden and in the encrypted
`/home/rishabh/.config/homelab/secrets.yaml` file.

## Secret File

Edit the local SOPS file with:

```bash
just secrets-edit
```

Or store/rotate the Cloudflare token interactively:

```bash
just cloudflare-store-token
```

Use this shape for the Cloudflare admin entry:

```yaml
cloudflare-admin.env: |
  CLOUDFLARE_API_TOKEN=cfut_replace_me
  CLOUDFLARE_ACCOUNT_ID=replace_me
  CLOUDFLARE_ZONE_ID=replace_me
  CLOUDFLARE_ZONE=therealrishabh.com
```

Then enable:

```nix
homelab.secrets.enable = true;
```

Apply:

```bash
just switch
```

Verify:

```bash
just secrets-check
cfctl verify
cfctl zones
cfctl dns
```

## Tunnel Login

Run:

```bash
cfctl tunnel-login
```

The command prints a Cloudflare login URL. Open it, select
`therealrishabh.com`, and return to the terminal.

Then create the tunnel:

```bash
cfctl tunnel-create therealrishabh-home
cfctl tunnel-list
```

Copy the generated tunnel credentials JSON into `cloudflared-tunnel.json` in
`/home/rishabh/.config/homelab/secrets.yaml`, set
`homelab.publicTunnel.tunnelId`, and switch.
