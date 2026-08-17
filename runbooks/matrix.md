# Private Matrix and Chat Bridges Runbook

The Matrix homeserver is private to the tailnet at:

```text
https://matrix.internal.therealrishabh.com
```

The preconfigured Cinny web client is available at:

```text
https://chat.internal.therealrishabh.com
```

Matrix IDs use the stable server name `therealrishabh.com`, for example
`@rishabh:therealrishabh.com`. Public registration and federation are disabled.

## Create the First User

Run this once on the server. It prompts for the password without putting it in
the shell history:

```bash
cd /srv/ops
just matrix-user-add rishabh
```

The daily account is not a Synapse administrator. It is an administrator of
the private WhatsApp and Instagram bridges only.

## Sign In From a Client

For a desktop browser, keep Tailscale connected and open
`https://chat.internal.therealrishabh.com`. The web client is locked to the
private homeserver, so only the username and password are required. Verify the
new browser session from Element X and do not use private browsing or clear its
site data unless Matrix Secure Backup is configured.

For native clients, use the following homeserver URL:

Install Element X on Android and Element Desktop on macOS. Choose a custom or
other homeserver and enter:

```text
https://matrix.internal.therealrishabh.com
```

Then sign in as `rishabh` with the password created above. Keep Tailscale
connected on the device. Verify the second Matrix device from the first and
set up the Matrix recovery key when Element offers it.

## Pair WhatsApp

In Element, start a direct chat with:

```text
@whatsappbot:therealrishabh.com
```

Send `login qr`. The bot returns a QR code. On the Android phone, open WhatsApp,
then use **Menu > Linked devices > Link a device** and scan the QR code.

WhatsApp creates encrypted Matrix rooms for recent conversations. Test both
directions with a trusted contact.

## Pair Google Messages

The server credentials are generated during initial deployment with
`just matrix-gmessages-store-secrets`. Re-running that command rotates them and
requires an immediate `just switch`; existing Google Messages login state may
need to be paired again after rotation.

In Element, start a direct chat with:

```text
@gmessagesbot:therealrishabh.com
```

Send `login google`. In a Firefox private window, open:

```text
https://accounts.google.com/AccountChooser?continue=https://messages.google.com/web/config
```

Keep developer tools open on the **Network** tab, reload the page, right-click
the `/web/config` request, and choose **Copy as cURL**. Send that complete cURL
command as the next message to the bridge bot. Treat it as a credential: send
it only in this encrypted bot management room, then close the private window
after pairing succeeds.

Google Messages on the phone will show an emoji confirmation prompt. Tap the
matching emoji to finish pairing. The phone must remain powered on, connected
to the internet, and able to run Google Messages for SMS and RCS bridging to
work. The old `login qr` flow is no longer supported by Google.

If Google Fi is in use, select the normal RCS-capable pairing mode rather than
"sync to your Google Account", which the bridge does not support. Test both
directions with a trusted contact. If a browser session makes the bridge
inactive, send `set-active` to the bot management room.

## Log In to Instagram

In Element, start a direct chat with:

```text
@instagrambot:therealrishabh.com
```

Send `login`. The bot replies with the Instagram login URL and waits for one
message containing either a cURL request or a JSON cookie object.

The simplest method uses desktop browser developer tools:

1. Sign in at `https://www.instagram.com/` and open the Direct inbox.
2. Open developer tools, select the **Network** panel, and reload the page.
3. Right-click a request to `www.instagram.com`, then choose **Copy as cURL**.
4. Paste the complete cURL command as the next message to the bridge bot.

As an alternative, send a JSON object containing the `sessionid`, `csrftoken`,
`ds_user_id`, `mid`, and `ig_did` cookies. These values are session credentials:
send them only to the encrypted bot management room and never to another user
or a shared room. The bridge redacts the credential message after receiving it.

If Instagram reports a challenge, checkpoint, or consent requirement, complete
it on the official Instagram site or app and repeat the login. The bridge does
not have a separate web login route.

## Connect the macOS iMessage Bridge

The Apple-dependent `mautrix-imessage` process runs inside the logged-in macOS
user session. It makes an outbound WebSocket connection over Tailscale to
`mautrix-wsproxy` on this server; no listener or inbound firewall rule is
needed on the Mac. Synapse reaches the proxy locally, and Caddy forwards only
the appservice WebSocket path from the private Matrix hostname.

The server provides a complete secret-bearing Mac configuration. Transfer it
directly into a mode-0600 file rather than printing it or copying its tokens:

```bash
install -d -m 0700 "$HOME/Library/Application Support/mautrix-imessage"
umask 077
ssh rishabh@100.73.159.103 'sudo matrix-imessage-export-config' \
  > "$HOME/Library/Application Support/mautrix-imessage/config.yaml"
```

The Mac must remain signed into Messages.app, logged into its desktop user,
awake, and connected to Tailscale. Keep SIP enabled and use the standard `mac`
connector. Grant the installed bridge binary Full Disk Access, Contacts access,
and Automation access to Messages when macOS asks.

The generated configuration uses `@imessagebot:therealrishabh.com`, creates a
personal iMessage space, encrypts portal rooms, enables appservice-based double
puppeting for `@rishabh:therealrishabh.com`, and backfills up to 100 messages
for conversations active in the previous 30 days. Protect the Mac bridge's
SQLite database and configuration as secrets.

## Talk to the Server Pi Agent

Start an encrypted direct chat in Element with:

```text
@pi:therealrishabh.com
```

The bot auto-joins the invite. Only `@rishabh:therealrishabh.com` is trusted;
messages from other users and unapproved group rooms are ignored. Send a normal
message to run Pi, or use `//status`, `//new`, `//model`, and `//thinking` in
Element when you need a literal Pi slash command.

Courier launches Pi in `/etc/agents`, a neutral root-owned, Nix-managed working
directory that ordinary Pi edit/write calls cannot modify. Its session and
Matrix encryption state live under `/srv/state/pi/courier`, separate from other
Pi sessions. The child agent uses `openai-codex/gpt-5.6-sol` at `medium`
thinking and runs as `rishabh`, including the server's passwordless sudo access.
That means a message accepted by this bot can administer the entire server;
keep the room encrypted, keep the bot account private, and do not enable it in
group rooms.

## Checks and Logs

```bash
cd /srv/ops
just matrix-doctor
just matrix-whatsapp-logs
just matrix-gmessages-logs
just matrix-instagram-logs
just matrix-imessage-proxy-logs
just matrix-pi-logs
```

## Maintain the Instagram bridge fork

The Instagram bridge is built from the committed `main` branch in
`/home/rishabh/Projects/mautrix-meta`. Its private GitHub backup is
`rishabhgoel0213/mautrix-meta`. The flake lock pins one exact commit and copies
it into the Nix store; the service never executes the mutable checkout directly.

After committing and testing a fork update, refresh only that source pin and
apply it through the normal validation gate:

```bash
cd /srv/ops
nix flake update mautrix-meta-homelab
just check
just switch
```

The fork deliberately emits ordinary Matrix `m.text` fallbacks for unknown,
unimplemented, unavailable view-once, or otherwise unbridgeable Instagram
activity. When a chat cannot be identified, the fallback goes to the Instagram
bridge management room. Keep notifications enabled for both portal rooms and
the management room.

The bridges store their session and encryption state under
`/srv/state/matrix/whatsapp`, `/srv/state/matrix/gmessages`, and
`/srv/state/matrix/instagram`. Synapse media and signing state are under
`/srv/state/matrix/synapse`; PostgreSQL holds message and bridge databases under
`/srv/state/matrix/postgresql`. A daily timer creates consistent database dumps
under `/srv/state/matrix/backups` for Backrest to capture. The iMessage bridge
database and attachment state remain on the Mac and need a separate Mac backup.
