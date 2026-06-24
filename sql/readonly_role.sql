-- Create a read-only PostgreSQL role for the NL query layer
-- This role can only SELECT, never write/DDL

CREATE ROLE nlq_readonly LOGIN PASSWORD 'changeme';
GRANT CONNECT ON DATABASE olist TO nlq_readonly;
GRANT USAGE ON SCHEMA public TO nlq_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nlq_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO nlq_readonly;
