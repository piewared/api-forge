#!/bin/sh
set -eu

# Required env (provided by your entrypoint/compose)
: "${APP_DB:?missing APP_DB}"
: "${APP_DB_OWNER:?missing APP_DB_OWNER}"   # NOLOGIN owner (app)
: "${APP_DB_USER:?missing APP_DB_USER}"               # app_user (LOGIN)
: "${APP_DB_RO_USER:?missing APP_DB_RO_USER}"         # app_ro  (LOGIN)
: "${TEMPORAL_DB_USER:?missing TEMPORAL_DB_USER}"               # e.g., temporal_user
: "${POSTGRES_APP_USER_PW:?missing POSTGRES_APP_USER_PW}"       # password for app user
: "${POSTGRES_APP_RO_PW:?missing POSTGRES_APP_RO_PW}"           # password for read-only user
: "${POSTGRES_TEMPORAL_PW:?missing POSTGRES_TEMPORAL_PW}"

# Optional override for Temporal owner (NOLOGIN). Default: "<temporal_user>_owner"
TEMPORAL_DB_OWNER="${TEMPORAL_DB_OWNER:-${TEMPORAL_DB_USER}_owner}"

# Database names (override if you like)
TEMPORAL_DB="${TEMPORAL_DB:-temporal}"
TEMPORAL_VIS_DB="${TEMPORAL_VIS_DB:-temporal_visibility}"

APP_SCHEMA="${APP_SCHEMA:-app}"

echo "==> Initializing roles/db for ${APP_DB} and Temporal"

psql -v ON_ERROR_STOP=1 \
  -v APP_DB="${APP_DB}" \
  -v APP_OWNER_USER="${APP_DB_OWNER}" \
  -v APP_USER="${APP_DB_USER}" \
  -v APP_RO_USER="${APP_DB_RO_USER}" \
  -v APP_USER_PASSWORD="${POSTGRES_APP_USER_PW}" \
  -v APP_RO_USER_PASSWORD="${POSTGRES_APP_RO_PW}" \
  -v TEMPORAL_OWNER_USER="${TEMPORAL_DB_OWNER}" \
  -v TEMPORAL_USER="${TEMPORAL_DB_USER}" \
  -v TEMPORAL_USER_PASSWORD="${POSTGRES_TEMPORAL_PW}" \
  -v TEMPORAL_DB="${TEMPORAL_DB}" \
  -v TEMPORAL_VIS_DB="${TEMPORAL_VIS_DB}" \
  -v APP_SCHEMA="${APP_SCHEMA}" <<'PSQL'
\set ON_ERROR_STOP on

\echo === Creating roles and database for :'APP_DB' ===

-- App: NOLOGIN owner (ownership container / default privileges anchor)
SELECT format('CREATE ROLE %I NOLOGIN', :'APP_OWNER_USER')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'APP_OWNER_USER')\gexec

-- App: LOGIN users
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'APP_USER', :'APP_USER_PASSWORD')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'APP_USER')\gexec

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'APP_RO_USER', :'APP_RO_USER_PASSWORD')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'APP_RO_USER')\gexec

-- App: database owned by NOLOGIN owner
SELECT format('CREATE DATABASE %I OWNER %I', :'APP_DB', :'APP_OWNER_USER')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'APP_DB')\gexec

\connect :APP_DB

CREATE EXTENSION IF NOT EXISTS btree_gin;

-- App: schema owned by NOLOGIN owner
SELECT format('CREATE SCHEMA %I AUTHORIZATION %I', :'APP_SCHEMA', :'APP_OWNER_USER')
WHERE NOT EXISTS (
  SELECT 1 FROM information_schema.schemata WHERE schema_name = :'APP_SCHEMA'
)\gexec

-- App: lock down
SELECT format('REVOKE CREATE ON DATABASE %I FROM PUBLIC', :'APP_DB')\gexec
SELECT format('REVOKE ALL ON SCHEMA %I FROM PUBLIC', :'APP_SCHEMA')\gexec

-- App: runtime grants
SELECT format('GRANT USAGE, CREATE ON SCHEMA %I TO %I', :'APP_SCHEMA', :'APP_USER')\gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO %I',
              :'APP_SCHEMA', :'APP_USER')\gexec
SELECT format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I',
              :'APP_SCHEMA', :'APP_USER')\gexec

SELECT format('GRANT USAGE ON SCHEMA %I TO %I', :'APP_SCHEMA', :'APP_RO_USER')\gexec
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I',
              :'APP_SCHEMA', :'APP_RO_USER')\gexec
SELECT format('GRANT SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I',
              :'APP_SCHEMA', :'APP_RO_USER')\gexec

-- App: future objects default privileges (for objects created by owner)
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
  :'APP_OWNER_USER', :'APP_SCHEMA', :'APP_USER'
)\gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON TABLES TO %I',
  :'APP_OWNER_USER', :'APP_SCHEMA', :'APP_RO_USER'
)\gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT USAGE, SELECT ON SEQUENCES TO %I',
  :'APP_OWNER_USER', :'APP_SCHEMA', :'APP_USER'
)\gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON SEQUENCES TO %I',
  :'APP_OWNER_USER', :'APP_SCHEMA', :'APP_RO_USER'
)\gexec

-- App: future objects default privileges (for objects created by app_user itself)
-- This ensures that when appuser creates tables directly (e.g., via SQLModel), 
-- the RO user automatically gets SELECT privileges
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON TABLES TO %I',
  :'APP_USER', :'APP_SCHEMA', :'APP_RO_USER'
)\gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON SEQUENCES TO %I',
  :'APP_USER', :'APP_SCHEMA', :'APP_RO_USER'
)\gexec

\echo === App DB/roles initialized (3-role pattern) ===


\echo === Creating Temporal roles and databases ===

-- Temporal: NOLOGIN owner
SELECT format('CREATE ROLE %I NOLOGIN', :'TEMPORAL_OWNER_USER')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'TEMPORAL_OWNER_USER')\gexec

-- Temporal: runtime/migration user (LOGIN)
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'TEMPORAL_USER', :'TEMPORAL_USER_PASSWORD')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'TEMPORAL_USER')\gexec

-- Temporal: databases (owned by NOLOGIN owner)
SELECT format('CREATE DATABASE %I OWNER %I', :'TEMPORAL_DB', :'TEMPORAL_OWNER_USER')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'TEMPORAL_DB')\gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'TEMPORAL_VIS_DB', :'TEMPORAL_OWNER_USER')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'TEMPORAL_VIS_DB')\gexec


-- ===== Configure DB: temporal =====
\connect :TEMPORAL_DB

CREATE EXTENSION IF NOT EXISTS btree_gin;

-- Lock down database and schema defaults
SELECT format('REVOKE CREATE ON DATABASE %I FROM PUBLIC', :'TEMPORAL_DB')\gexec
-- If you don't use public for anything else, you can also harden it:
-- REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- Allow Temporal to run migrations (CREATE) and operate (USAGE) in public schema
SELECT format('GRANT USAGE, CREATE ON SCHEMA public TO %I', :'TEMPORAL_USER')\gexec

-- Default privileges for future objects owned by NOLOGIN owner
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public
     GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLES TO %I',
  :'TEMPORAL_OWNER_USER', :'TEMPORAL_USER'
)\gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public
     GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I',
  :'TEMPORAL_OWNER_USER', :'TEMPORAL_USER'
)\gexec

-- Align privileges for any existing objects (first run usually none)
SELECT format(
  'GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public TO %I',
  :'TEMPORAL_USER'
)\gexec
SELECT format(
  'GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO %I',
  :'TEMPORAL_USER'
)\gexec


-- ===== Configure DB: temporal_visibility =====
\connect :TEMPORAL_VIS_DB

CREATE EXTENSION IF NOT EXISTS btree_gin;

SELECT format('REVOKE CREATE ON DATABASE %I FROM PUBLIC', :'TEMPORAL_VIS_DB')\gexec
SELECT format('GRANT USAGE, CREATE ON SCHEMA public TO %I', :'TEMPORAL_USER')\gexec

SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public
     GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLES TO %I',
  :'TEMPORAL_OWNER_USER', :'TEMPORAL_USER'
)\gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public
     GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I',
  :'TEMPORAL_OWNER_USER', :'TEMPORAL_USER'
)\gexec

SELECT format(
  'GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public TO %I',
  :'TEMPORAL_USER'
)\gexec
SELECT format(
  'GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO %I',
  :'TEMPORAL_USER'
)\gexec

\echo === Temporal roles/databases created. Temporal user can migrate & run with least privilege. ===
\echo === Next: run temporal-sql-tool setup-schema in both DBs ===
-- Example (outside this script):
--   temporal-sql-tool --plugin postgres --ep localhost -p 5432 -u :'TEMPORAL_USER' -pw '<pw>' --db :'TEMPORAL_DB'       setup-schema --schema-name postgres
--   temporal-sql-tool --plugin postgres --ep localhost -p 5432 -u :'TEMPORAL_USER' -pw '<pw>' --db :'TEMPORAL_VIS_DB'  setup-schema --schema-name postgres

PSQL

echo "==> Init completed"
