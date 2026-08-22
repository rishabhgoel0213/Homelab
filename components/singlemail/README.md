# Singlemail Runbook

Singlemail creates purpose-scoped receive-only addresses at
`inbox.therealrishabh.com`. Addresses use 24-character cryptographically random
local parts. Cloudflare Email Routing invokes the `singlemail` Worker, D1
stores inbox and message metadata, and R2 stores raw MIME for 24
hours. The management UI is private at:

```text
https://maildrop.internal.therealrishabh.com
```

## Normal use

```bash
singlemail create --purpose "authorized example.com signup" --ttl 1h --json
singlemail wait <inbox-id> --timeout 5m --json
singlemail code <inbox-id> --timeout 5m
singlemail links <inbox-id> --timeout 5m
singlemail close <inbox-id>
```

Promote an address before using it for an account that may need password
recovery:

```bash
singlemail promote <inbox-id>
```

Promotion keeps the address active. Message bodies and metadata still expire
after 24 hours. Singlemail does not send email and must not be used to evade
account limits, bans, identity checks, or a site's terms.

## Deploy

The Worker configuration lives in `cloudflare/singlemail`. Deploy code,
migrations, MX records, and the Worker catch-all with:

```bash
just singlemail-deploy
```

That command requires the host Cloudflare token to have Workers Scripts Edit,
D1 Edit, R2 Edit, and Email Routing Edit permissions. The token deployed on
2026-08-12 lacks the first three permissions; the initial live deployment used
the connected Cloudflare account instead. Rotate the host token before relying
on this recipe for an unattended redeploy.

Generate and install the shared API token in the Worker and the SOPS file:

```bash
just singlemail-store-token
```

After changing the NixOS module or rotating the token:

```bash
just check
just switch
singlemail doctor --json
```

## Verification

```bash
systemctl is-active singlemail.service
curl --fail --silent https://maildrop.internal.therealrishabh.com/health | jq .
dig MX inbox.therealrishabh.com
singlemail doctor --json
```

Create a short-lived inbox, send it a message from an external provider, then
verify `singlemail code` or `singlemail links`. Close and delete the test inbox
when finished.

## Privacy and recovery

- Unknown, expired, closed, full, wrong-domain, and oversized recipients are rejected.
- The public Worker API requires a 256-bit bearer token stored only as a Worker
  secret and in SOPS-managed `/run/secrets/singlemail.env`.
- The private gateway sanitizes email into inert text. It never renders remote
  email HTML or exposes the Worker token to the browser.
- The Worker cron closes expired inboxes and removes messages after 24 hours.
  R2 also has a lifecycle rule as a storage-level backstop.
- Re-run `just singlemail-store-token`, `just switch`, and the verification
  commands to rotate a suspected token.
