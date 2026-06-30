-- App-state schema (B1 + B2).
-- Idempotent: safe to re-run. B3 will add `sessions` and `messages` tables.

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,            -- uuid
  email         TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,               -- argon2id encoded hash
  role          TEXT,                         -- reserved; RBAC deferred
  created_at    TEXT NOT NULL                 -- ISO 8601 UTC
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  id          TEXT PRIMARY KEY,              -- random uuid; the cookie value
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  TEXT NOT NULL,                  -- ISO 8601 UTC
  expires_at  TEXT NOT NULL                   -- ISO 8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user
  ON auth_sessions(user_id);
