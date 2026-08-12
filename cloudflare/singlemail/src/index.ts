const MAX_API_BODY_BYTES = 16 * 1024;
const MAX_MESSAGE_BYTES = 5 * 1024 * 1024;
const DEFAULT_TTL_SECONDS = 60 * 60;
const MIN_TTL_SECONDS = 5 * 60;
const MAX_TTL_SECONDS = 7 * 24 * 60 * 60;
const DEFAULT_MAX_MESSAGES = 5;
const MAX_MESSAGES = 20;
const MESSAGE_RETENTION_SECONDS = 24 * 60 * 60;
const RANDOM_LOCAL_PART_PATTERN = /^[0-9a-f]{24}$/;

interface InboxRow {
  id: string;
  local_part: string;
  address: string;
  purpose: string;
  created_at: number;
  expires_at: number | null;
  closed_at: number | null;
  promoted: number;
  max_messages: number;
  message_count: number;
}

interface MessageRow {
  id: string;
  inbox_id: string;
  r2_key: string;
  envelope_from: string;
  envelope_to: string;
  subject: string;
  message_id: string;
  received_at: number;
  size: number;
}

interface CreateInboxInput {
  purpose: string;
  ttl_seconds: number;
  max_messages: number;
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function json(data: unknown, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json; charset=utf-8");
  headers.set("Cache-Control", "no-store");
  headers.set("X-Content-Type-Options", "nosniff");
  return Response.json(data, { ...init, headers });
}

function errorResponse(status: number, code: string, message: string): Response {
  return json({ error: { code, message } }, { status });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function integerInRange(value: unknown, fallback: number, minimum: number, maximum: number): number | null {
  const candidate = value === undefined ? fallback : value;
  if (typeof candidate !== "number" || !Number.isInteger(candidate)) {
    return null;
  }
  if (candidate < minimum || candidate > maximum) {
    return null;
  }
  return candidate;
}

async function readJsonBody(request: Request): Promise<unknown> {
  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (contentLength > MAX_API_BODY_BYTES) {
    throw new RangeError("Request body is too large");
  }
  const bytes = await request.bytes();
  if (bytes.byteLength > MAX_API_BODY_BYTES) {
    throw new RangeError("Request body is too large");
  }
  if (bytes.byteLength === 0) {
    return {};
  }
  return JSON.parse(new TextDecoder().decode(bytes)) as unknown;
}

async function verifyToken(provided: string, expected: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return crypto.subtle.timingSafeEqual(providedHash, expectedHash);
}

async function authorized(request: Request, env: Env): Promise<boolean> {
  const authorization = request.headers.get("authorization") ?? "";
  const prefix = "Bearer ";
  const provided = authorization.startsWith(prefix) ? authorization.slice(prefix.length) : "";
  return verifyToken(provided, env.SINGLEMAIL_API_TOKEN);
}

function randomHex(bytes: number): string {
  const value = new Uint8Array(bytes);
  crypto.getRandomValues(value);
  return Array.from(value, (item) => item.toString(16).padStart(2, "0")).join("");
}

function normalizeInbox(row: InboxRow): Record<string, unknown> {
  const now = nowSeconds();
  const active = row.closed_at === null && (row.expires_at === null || row.expires_at > now);
  return {
    id: row.id,
    address: row.address,
    purpose: row.purpose,
    created_at: row.created_at,
    expires_at: row.expires_at,
    closed_at: row.closed_at,
    promoted: row.promoted === 1,
    max_messages: row.max_messages,
    message_count: row.message_count,
    active,
  };
}

function normalizeMessage(row: MessageRow): Record<string, unknown> {
  return {
    id: row.id,
    inbox_id: row.inbox_id,
    envelope_from: row.envelope_from,
    envelope_to: row.envelope_to,
    subject: row.subject,
    message_id: row.message_id,
    received_at: row.received_at,
    size: row.size,
  };
}

function parseCreateInbox(value: unknown): CreateInboxInput | null {
  if (!isRecord(value)) {
    return null;
  }
  const purpose = typeof value.purpose === "string" ? value.purpose.trim() : "";
  if (purpose.length < 1 || purpose.length > 200) {
    return null;
  }
  const ttl = integerInRange(value.ttl_seconds, DEFAULT_TTL_SECONDS, MIN_TTL_SECONDS, MAX_TTL_SECONDS);
  const maxMessages = integerInRange(value.max_messages, DEFAULT_MAX_MESSAGES, 1, MAX_MESSAGES);
  if (ttl === null || maxMessages === null) {
    return null;
  }
  return { purpose, ttl_seconds: ttl, max_messages: maxMessages };
}

async function createInbox(env: Env, input: CreateInboxInput): Promise<InboxRow> {
  const createdAt = nowSeconds();
  const expiresAt = createdAt + input.ttl_seconds;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const id = crypto.randomUUID();
    const localPart = randomHex(12);
    const address = `${localPart}@${env.INBOX_DOMAIN}`;
    try {
      await env.DB.prepare(
        `INSERT INTO inboxes(
          id, local_part, address, purpose, created_at, expires_at,
          closed_at, promoted, max_messages, message_count
        ) VALUES(?, ?, ?, ?, ?, ?, NULL, 0, ?, 0)`,
      )
        .bind(id, localPart, address, input.purpose, createdAt, expiresAt, input.max_messages)
        .run();
      const row = await env.DB.prepare("SELECT * FROM inboxes WHERE id = ?").bind(id).first<InboxRow>();
      if (row !== null) {
        return row;
      }
    } catch (error) {
      if (attempt === 3) {
        throw error;
      }
    }
  }
  throw new Error("Could not allocate an inbox");
}

async function getInbox(env: Env, id: string): Promise<InboxRow | null> {
  return env.DB.prepare("SELECT * FROM inboxes WHERE id = ?").bind(id).first<InboxRow>();
}

async function listMessages(env: Env, inboxId: string): Promise<MessageRow[]> {
  const result = await env.DB.prepare(
    "SELECT * FROM messages WHERE inbox_id = ? ORDER BY received_at DESC, id DESC",
  )
    .bind(inboxId)
    .all<MessageRow>();
  return result.results;
}

async function closeInbox(env: Env, id: string): Promise<InboxRow | null> {
  await env.DB.prepare(
    "UPDATE inboxes SET closed_at = COALESCE(closed_at, ?) WHERE id = ?",
  )
    .bind(nowSeconds(), id)
    .run();
  return getInbox(env, id);
}

async function promoteInbox(env: Env, id: string): Promise<InboxRow | null> {
  await env.DB.prepare(
    "UPDATE inboxes SET promoted = 1, expires_at = NULL, closed_at = NULL WHERE id = ?",
  )
    .bind(id)
    .run();
  return getInbox(env, id);
}

async function deleteInbox(env: Env, id: string): Promise<boolean> {
  const messages = await listMessages(env, id);
  if (messages.length > 0) {
    await env.MESSAGES.delete(messages.map((message) => message.r2_key));
  }
  const result = await env.DB.prepare("DELETE FROM inboxes WHERE id = ?").bind(id).run();
  return Number(result.meta.changes ?? 0) > 0;
}

async function streamRawMessage(env: Env, inboxId: string, messageId: string): Promise<Response> {
  const message = await env.DB.prepare(
    "SELECT * FROM messages WHERE id = ? AND inbox_id = ?",
  )
    .bind(messageId, inboxId)
    .first<MessageRow>();
  if (message === null) {
    return errorResponse(404, "message_not_found", "Message not found");
  }
  const object = await env.MESSAGES.get(message.r2_key);
  if (object === null) {
    return errorResponse(410, "message_body_expired", "Message body has expired");
  }
  return new Response(object.body, {
    headers: {
      "Content-Type": "message/rfc822",
      "Content-Length": String(object.size),
      "Cache-Control": "no-store",
      "Content-Disposition": `attachment; filename="${message.id}.eml"`,
      "X-Content-Type-Options": "nosniff",
    },
  });
}

async function handleApi(request: Request, env: Env): Promise<Response> {
  if (!(await authorized(request, env))) {
    return errorResponse(401, "unauthorized", "A valid bearer token is required");
  }

  const url = new URL(request.url);
  const segments = url.pathname.split("/").filter(Boolean);

  if (request.method === "POST" && url.pathname === "/v1/inboxes") {
    let body: unknown;
    try {
      body = await readJsonBody(request);
    } catch (error) {
      const message = error instanceof RangeError ? error.message : "Request body must be valid JSON";
      return errorResponse(error instanceof RangeError ? 413 : 400, "invalid_request", message);
    }
    const input = parseCreateInbox(body);
    if (input === null) {
      return errorResponse(
        400,
        "invalid_request",
        "purpose, ttl_seconds (300-604800), and max_messages (1-20) must be valid",
      );
    }
    const inbox = await createInbox(env, input);
    return json({ inbox: normalizeInbox(inbox) }, { status: 201 });
  }

  if (request.method === "GET" && url.pathname === "/v1/inboxes") {
    const includeAll = url.searchParams.get("status") === "all";
    const current = nowSeconds();
    const query = includeAll
      ? "SELECT * FROM inboxes ORDER BY created_at DESC LIMIT 200"
      : `SELECT * FROM inboxes
         WHERE closed_at IS NULL AND (expires_at IS NULL OR expires_at > ?)
         ORDER BY created_at DESC LIMIT 200`;
    const statement = env.DB.prepare(query);
    const result = includeAll
      ? await statement.all<InboxRow>()
      : await statement.bind(current).all<InboxRow>();
    return json({ inboxes: result.results.map(normalizeInbox) });
  }

  if (segments.length >= 3 && segments[0] === "v1" && segments[1] === "inboxes") {
    const inboxId = segments[2];
    const inbox = await getInbox(env, inboxId);
    if (inbox === null) {
      return errorResponse(404, "inbox_not_found", "Inbox not found");
    }

    if (request.method === "GET" && segments.length === 3) {
      return json({ inbox: normalizeInbox(inbox) });
    }

    if (request.method === "POST" && segments.length === 4 && segments[3] === "close") {
      const updated = await closeInbox(env, inboxId);
      return json({ inbox: normalizeInbox(updated ?? inbox) });
    }

    if (request.method === "POST" && segments.length === 4 && segments[3] === "promote") {
      const updated = await promoteInbox(env, inboxId);
      return json({ inbox: normalizeInbox(updated ?? inbox) });
    }

    if (request.method === "DELETE" && segments.length === 3) {
      await deleteInbox(env, inboxId);
      return new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
    }

    if (request.method === "GET" && segments.length === 4 && segments[3] === "messages") {
      const messages = await listMessages(env, inboxId);
      return json({ inbox: normalizeInbox(inbox), messages: messages.map(normalizeMessage) });
    }

    if (
      request.method === "GET" &&
      segments.length === 6 &&
      segments[3] === "messages" &&
      segments[5] === "raw"
    ) {
      return streamRawMessage(env, inboxId, segments[4]);
    }
  }

  return errorResponse(404, "not_found", "Endpoint not found");
}

function limitedHeader(headers: Headers, name: string, maximum: number): string {
  return (headers.get(name) ?? "").replace(/[\r\n]+/g, " ").slice(0, maximum);
}

async function receiveEmail(message: ForwardableEmailMessage, env: Env): Promise<void> {
  const to = message.to.trim().toLowerCase();
  const separator = to.lastIndexOf("@");
  if (separator < 1 || to.slice(separator + 1) !== env.INBOX_DOMAIN.toLowerCase()) {
    message.setReject("Recipient unavailable");
    return;
  }
  if (message.rawSize > MAX_MESSAGE_BYTES) {
    message.setReject("Message exceeds this mailbox's size limit");
    return;
  }

  const localPart = to.slice(0, separator);
  if (!RANDOM_LOCAL_PART_PATTERN.test(localPart)) {
    message.setReject("Recipient unavailable");
    return;
  }
  const current = nowSeconds();
  const reserved = await env.DB.prepare(
    `UPDATE inboxes
     SET message_count = message_count + 1
     WHERE local_part = ?
       AND closed_at IS NULL
       AND (expires_at IS NULL OR expires_at > ?)
       AND message_count < max_messages
     RETURNING *`,
  )
    .bind(localPart, current)
    .first<InboxRow>();

  if (reserved === null) {
    message.setReject("Recipient unavailable");
    return;
  }

  const messageId = crypto.randomUUID();
  const r2Key = `messages/${reserved.id}/${messageId}.eml`;
  try {
    const fixedLength = new FixedLengthStream(message.rawSize);
    await Promise.all([
      message.raw.pipeTo(fixedLength.writable),
      env.MESSAGES.put(r2Key, fixedLength.readable, {
        httpMetadata: { contentType: "message/rfc822" },
      }),
    ]);
    await env.DB.prepare(
      `INSERT INTO messages(
        id, inbox_id, r2_key, envelope_from, envelope_to,
        subject, message_id, received_at, size
      ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
      .bind(
        messageId,
        reserved.id,
        r2Key,
        message.from.slice(0, 320),
        message.to.slice(0, 320),
        limitedHeader(message.headers, "subject", 998),
        limitedHeader(message.headers, "message-id", 998),
        current,
        message.rawSize,
      )
      .run();
  } catch (error) {
    await Promise.all([
      env.MESSAGES.delete(r2Key),
      env.DB.prepare(
        "UPDATE inboxes SET message_count = MAX(message_count - 1, 0) WHERE id = ?",
      )
        .bind(reserved.id)
        .run(),
    ]);
    throw error;
  }

  console.log(JSON.stringify({ event: "email_stored", inbox_id: reserved.id, message_id: messageId }));
}

async function cleanup(env: Env): Promise<void> {
  const current = nowSeconds();
  const cutoff = current - MESSAGE_RETENTION_SECONDS;
  await env.DB.prepare(
    "UPDATE inboxes SET closed_at = ? WHERE closed_at IS NULL AND expires_at IS NOT NULL AND expires_at <= ?",
  )
    .bind(current, current)
    .run();

  const stale = await env.DB.prepare(
    "SELECT * FROM messages WHERE received_at <= ? ORDER BY received_at LIMIT 90",
  )
    .bind(cutoff)
    .all<MessageRow>();
  if (stale.results.length > 0) {
    await env.MESSAGES.delete(stale.results.map((message) => message.r2_key));
    const messagePlaceholders = stale.results.map(() => "?").join(",");
    const inboxIds = [...new Set(stale.results.map((message) => message.inbox_id))];
    const inboxPlaceholders = inboxIds.map(() => "?").join(",");
    await env.DB.batch([
      env.DB.prepare(`DELETE FROM messages WHERE id IN (${messagePlaceholders})`).bind(
        ...stale.results.map((message) => message.id),
      ),
      env.DB.prepare(
        `UPDATE inboxes
         SET message_count = (SELECT COUNT(*) FROM messages WHERE messages.inbox_id = inboxes.id)
         WHERE id IN (${inboxPlaceholders})`,
      ).bind(...inboxIds),
    ]);
  }
  console.log(JSON.stringify({ event: "cleanup_complete", messages_deleted: stale.results.length }));
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      const database = await env.DB.prepare("SELECT 1 AS ready").first<{ ready: number }>();
      return json({ ready: database?.ready === 1, service: "singlemail" });
    }
    try {
      return await handleApi(request, env);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      console.error(JSON.stringify({ event: "api_error", path: url.pathname, detail }));
      return errorResponse(500, "internal_error", "The request could not be completed");
    }
  },

  async email(message: ForwardableEmailMessage, env: Env): Promise<void> {
    try {
      await receiveEmail(message, env);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      console.error(JSON.stringify({ event: "email_error", detail }));
      throw error;
    }
  },

  async scheduled(_controller: ScheduledController, env: Env): Promise<void> {
    try {
      await cleanup(env);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      console.error(JSON.stringify({ event: "cleanup_error", detail }));
      throw error;
    }
  },
} satisfies ExportedHandler<Env>;
