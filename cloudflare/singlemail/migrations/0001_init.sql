PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS inboxes (
  id TEXT PRIMARY KEY,
  local_part TEXT NOT NULL UNIQUE,
  address TEXT NOT NULL UNIQUE,
  purpose TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER,
  closed_at INTEGER,
  promoted INTEGER NOT NULL DEFAULT 0 CHECK (promoted IN (0, 1)),
  max_messages INTEGER NOT NULL CHECK (max_messages BETWEEN 1 AND 20),
  message_count INTEGER NOT NULL DEFAULT 0 CHECK (message_count >= 0)
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  inbox_id TEXT NOT NULL REFERENCES inboxes(id) ON DELETE CASCADE,
  r2_key TEXT NOT NULL UNIQUE,
  envelope_from TEXT NOT NULL,
  envelope_to TEXT NOT NULL,
  subject TEXT NOT NULL,
  message_id TEXT NOT NULL,
  received_at INTEGER NOT NULL,
  size INTEGER NOT NULL CHECK (size >= 0)
);

CREATE INDEX IF NOT EXISTS inboxes_active_idx
  ON inboxes(closed_at, expires_at, created_at);

CREATE INDEX IF NOT EXISTS messages_inbox_received_idx
  ON messages(inbox_id, received_at DESC);

CREATE INDEX IF NOT EXISTS messages_retention_idx
  ON messages(received_at);
