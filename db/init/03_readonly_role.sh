#!/bin/sh
# Creates the SELECT-only role used by the MCP server.
# The admin user (POSTGRES_USER) is only used for schema + seed; the server never sees it.
set -eu

RO_USER="${SALESTALK_RO_USER:-salestalk_ro}"
RO_PASSWORD="${SALESTALK_RO_PASSWORD:-salestalk_ro_password}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v ro_user="$RO_USER" -v ro_password="$RO_PASSWORD" -v db_name="$POSTGRES_DB" <<'EOSQL'
-- 1. A login role with no special powers.
SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 20',
    :'ro_user', :'ro_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'ro_user') \gexec

-- 2. Nobody but the owner may create objects or temp tables.
REVOKE CREATE, TEMPORARY ON DATABASE :"db_name" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- 3. Read access only: connect, see the schema, SELECT tables/views (now and in future).
GRANT CONNECT ON DATABASE :"db_name" TO :"ro_user";
GRANT USAGE ON SCHEMA public TO :"ro_user";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"ro_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO :"ro_user";

-- 4. Safe session defaults even if a client forgets them.
ALTER ROLE :"ro_user" SET default_transaction_read_only = on;
ALTER ROLE :"ro_user" SET statement_timeout = '5s';
ALTER ROLE :"ro_user" SET idle_in_transaction_session_timeout = '15s';
ALTER ROLE :"ro_user" SET search_path = public;
EOSQL

echo "SalesTalk: read-only role '$RO_USER' is ready."
