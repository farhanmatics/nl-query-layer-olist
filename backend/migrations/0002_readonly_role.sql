-- 0002_readonly_role.sql
-- Create the SELECT-only role the backend connects as. Idempotent: the role is
-- only created if missing, and grants are safe to re-apply.
--
-- SECURITY: the default password is 'changeme'. Change it (and your .env DB_URL)
-- before any non-local use:
--   ALTER ROLE nlq_readonly WITH PASSWORD 'your-strong-password';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nlq_readonly') THEN
        CREATE ROLE nlq_readonly LOGIN PASSWORD 'changeme';
    END IF;
END $$;

-- Grant CONNECT on whatever database this migration is running against.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO nlq_readonly', current_database());
END $$;

GRANT USAGE ON SCHEMA public TO nlq_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nlq_readonly;

-- Ensure tables created in the future are also readable.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO nlq_readonly;
