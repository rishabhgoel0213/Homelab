# UMD Canvas Bridge

The Canvas bridge creates a read-only local mirror of current UMD courses and
exposes that mirror to Codex through the `umd-canvas` local plugin. It follows
the Canvas Student Android OAuth flow because UMD does not issue ordinary
developer keys to student accounts.

The bridge never accepts or stores a UMD password. UMD login and Duo approval
happen on UMD's real pages. The resulting Canvas OAuth access and refresh tokens
are stored in `/srv/state/canvas-bridge/canvas.db`, which is mode `0600` inside
a mode `0700` service directory owned by `rishabh`.

## First login

Generate a one-time code from the server:

```bash
just canvas-pair
```

Open `https://canvas.internal.therealrishabh.com`, enter that code, and choose
**Continue to UMD login**. Complete the UMD login and Duo prompt.

Canvas's mobile OAuth registration uses a fixed callback. The browser will stop
on a **Page Not Found** screen at `sso.canvaslms.com`; this is expected because
the official Android app normally intercepts that URL before it renders. Copy
the entire address-bar URL. Return to the bridge, choose **I already completed
UMD login**, paste the URL, and complete the connection.

The callback contains a one-time authorization code. The bridge does not log
the URL or code. It exchanges the code directly with Canvas and immediately
starts the first sync.

## Normal operation

The service attempts a read-only sync every 15 minutes. A sync fetches:

- active courses and term metadata;
- the instructor-curated module and module-item order;
- assignments and due dates;
- recent announcements;
- module-linked pages;
- module-linked files up to 50 MiB when their type is suitable for text
  extraction.

PDF text is extracted with `pdftotext`. Text, HTML, Markdown, CSV, JSON, DOCX,
PPTX, and XLSX files receive lightweight local text extraction. Videos and
other large binary files remain metadata-only.

Useful operator commands:

```bash
just canvas-doctor
just canvas-status
just canvas-sync
just canvas-pair
```

For a quick targeted refresh while working in one class:

```bash
canvas-bridge sync --course-id 1401732
```

`canvas-doctor` verifies state-directory access, UMD's Canvas mobile OAuth
compatibility, and the PDF extraction backend. It does not initiate login or
read course content.

## Security boundary

- The web interface binds only to `127.0.0.1` and is exposed only through the
  normal tailnet-only internal route.
- Tailnet web access requires a one-time pairing code and receives an
  authenticated, signed, `Secure`, `HttpOnly`, `SameSite=Strict` cookie.
- State-changing web requests use CSRF protection.
- Canvas API synchronization performs GET requests only. The only non-GET
  Canvas operations are OAuth token exchange, refresh, and explicit token
  revocation during disconnect.
- OAuth client material is requested from Canvas's mobile verification service
  when needed and is not persisted.
- Signed Canvas file-download URLs and OAuth tokens are excluded from tool
  output and application logs.

The Android-compatible mobile verification protocol is not a documented
third-party integration contract. It can change or be disabled by Instructure
or UMD. The MCP and local-mirror boundary is deliberately independent of that
authentication transport so a future UMD-issued developer key can replace it
without changing the Codex tools.

The bridge's mobile-protocol provenance and the license of the implementation
used as an interoperability reference are documented in
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md). No Canvas Android source
or binary is included in the bridge.

External LTI tools such as Gradescope, Panopto, or publisher platforms may
require separate authorization and are not automatically mirrored.
