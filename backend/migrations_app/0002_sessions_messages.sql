-- B3: chat sessions + message history.
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS sessions (
  id             TEXT PRIMARY KEY,           -- uuid
  user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title          TEXT,                       -- backend-derived from first question
  created_at     TEXT NOT NULL,              -- ISO 8601 UTC
  last_active_at TEXT NOT NULL               -- ISO 8601 UTC; updated on each turn
);

CREATE INDEX IF NOT EXISTS idx_sessions_user
  ON sessions(user_id, last_active_at DESC);

CREATE TABLE IF NOT EXISTS messages (
  id             TEXT PRIMARY KEY,          -- uuid
  session_id     TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role           TEXT NOT NULL,             -- 'user' | 'assistant'
  question       TEXT,                       -- user turn text (NULL for assistant rows)
  response_json  TEXT,                       -- full QueryResponse (assistant rows)
  resolved_call  TEXT,                       -- JSON: {operation, args} — the durable
                                             --   equivalent of B0's in-memory state.
                                             --   NULL for clarify/error/empty turns.
  created_at     TEXT NOT NULL               -- ISO 8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_messages_session
  ON messages(session_id, created_at);
