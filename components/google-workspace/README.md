# Google Workspace CLI (`gog`)

Shared, harness-neutral CLI access to Google Drive, Google Calendar, Gmail,
Docs, and Sheets via `gogcli` (`gog`). Because `gog` is an ordinary command on
`PATH`, Codex, Claude Code, Antigravity CLI, Antigravity T3 ACP, and scripts
all share the same integration and login without per-harness MCP configuration.

## Server state

On `nixos-pc`, the managed `gog` wrapper stores config and encrypted OAuth
tokens under `/srv/state/google-workspace` (mode `0700`, owned by `rishabh`,
included in Backrest `/srv/state` backups):

- `/srv/state/google-workspace/config/gogcli/` — `gog` config, OAuth client
  credentials (`credentials.json`), and encrypted file-keyring tokens.
- `/srv/state/google-workspace/keyring.key` — auto-generated mode-`0600` key
  used for the headless `file` keyring backend so non-interactive agent shells
  do not prompt for a passphrase.
- `/srv/state/google-workspace/default-account` — optional single-line file
  containing your default Google email address (exported as `GOG_ACCOUNT` when
  not overridden with `-a`/`--account`).

On the MacBook, `gog` uses macOS Keychain directly. Credentials are not copied
between hosts.

## One-time headless setup on `nixos-pc`

1. In Google Cloud Console → **APIs & Services → Credentials**, create an
   **OAuth client ID** of type **Desktop app** and enable the Gmail, Google
   Calendar, Google Drive, Google Docs, and Google Sheets APIs.
2. Copy the downloaded JSON to `/tmp/google-client.json` (mode `0600`) and
   import it into `gog`:
   ```bash
   gog auth credentials set /tmp/google-client.json
   rm -f /tmp/google-client.json
   ```
3. Complete the headless OAuth login over SSH (choose `--readonly` if you want
   strictly read-only tokens, or omit it for full access):
   ```bash
   gog auth add you@gmail.com --manual --services=gmail,calendar,drive,docs,sheets
   ```
   Open the printed URL in your browser, approve consent, and paste the
   redirect URL back into the terminal.
4. Set your default account so `--account` is optional:
   ```bash
   printf '%s\n' you@gmail.com > /srv/state/google-workspace/default-account
   chmod 0600 /srv/state/google-workspace/default-account
   ```
5. Verify:
   ```bash
   gog auth status
   gog auth list
   gog drive ls --json
   ```

## Common commands

```bash
gog gmail search "is:unread" --json
gog gmail get <messageId> --json
gog calendar events primary --from today --days 7 --json
gog drive ls --json
gog drive search "fullText contains 'syllabus'" --json
gog drive download <fileId> --out /tmp/file.pdf
```
