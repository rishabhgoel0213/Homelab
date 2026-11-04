# Bootstrap Runbook

## 1. Install The Ops Repo

On a new server, create both Git checkouts (the targets must not already exist):

```bash
sudo install -d -m 0755 -o rishabh -g users /home/rishabh/Projects /srv/ops
git clone https://github.com/rishabhgoel0213/Homelab.git /home/rishabh/Projects/Homelab
git clone /home/rishabh/Projects/Homelab /srv/ops
git -C /srv/ops remote set-url origin https://github.com/rishabhgoel0213/Homelab.git
cd /home/rishabh/Projects/Homelab
```

Set this clone's local Git `user.name` and `user.email` before committing.

## 2. Generate The sops Recipient

Use the server SSH host key as the age recipient. From an admin workstation with `ssh-to-age`:

```bash
ssh-keyscan nixos-pc | ssh-to-age
```

Replace the placeholder recipient in `.sops.yaml`.

## 3. Create Cloudflare Credentials

Create Cloudflare API tokens as described in `../../components/cloudflare/README.md`.

At minimum, ACME DNS-01 needs:

- Zone: DNS: Edit
- Zone: Zone: Read
- Scope: `therealrishabh.com`

Then create a tunnel:

```bash
just cloudflare-login
just cloudflare-create-tunnel therealrishabh-home
```

Cloudflare will print an interactive login URL. Complete that in your browser.

Create public DNS records in Cloudflare:

```text
therealrishabh.com       CNAME <tunnel-id>.cfargotunnel.com
*.therealrishabh.com     CNAME <tunnel-id>.cfargotunnel.com
```

Keep `*.internal.therealrishabh.com` out of public DNS.

## 4. Create The Local Sops File

```bash
just secrets-edit
just secrets-check
```

The encrypted file lives at:

```text
/home/rishabh/.config/homelab/secrets.yaml
```

Use `../security/homelab-secrets.example.yaml` as the shape reference.

The file must contain:

- `network-manager.env`
- `cloudflare-admin.env`
- `cloudflare-dns.env`
- `cloudflared-tunnel.json`
- `codex-auth.json`
- `codex-credentials.json`
- `vaultwarden.env`
- `restic-password`
- `restic-ssh-key` and `restic-known-hosts` if using Restic over SSH/SFTP

## 5. Enable Services

Edit `hosts/nixos-pc/default.nix`:

```nix
homelab = {
  tailnetIp = "100.x.y.z";

  secrets.enable = true;
  acme.enable = true;

  publicTunnel = {
    enable = true;
    tunnelId = "00000000-0000-0000-0000-000000000000";
  };

  privateDns.enable = true;
  vaultwarden.enable = true;
  backrest = {
    enable = true;
    repository = "sftp:u123456@u123456.your-storagebox.de:/home/homelab";
    sshTarget = "u123456@u123456.your-storagebox.de";
    sshPort = 23;
  };
};
```

Then:

```bash
git add .
git commit -m "homelab: configure server bootstrap"
just deploy
```

## 6. Configure Tailscale Split DNS

In the Tailscale admin console, add a restricted nameserver:

```text
Domain: internal.therealrishabh.com
Nameserver: <server tailnet IP>
```

Clients must use Tailscale DNS settings for this to apply.
