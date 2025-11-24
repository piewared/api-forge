#!/usr/bin/env bash
set -euo pipefail

log() {
    printf '[sync-passwords] %s\n' "$1" >&2
}

KEYS_DIR=${KEYS_DIR:-/app/keys}
SECRETS_SOURCE_DIR=${SECRETS_SOURCE_DIR:-/run/secrets}
PREFER_SECRET_FILES=${PREFER_SECRET_FILES:-true}

require_env() {
    local name="$1"
    if ! printenv "$name" >/dev/null 2>&1; then
        log "ERROR: missing required env var $name"
        exit 1
    fi
}

read_secret_value() {
    local env_name="$1"
    local file_name="$2"

    # Prefer reading from live secret files so rotations apply without container restarts
    if [ "$PREFER_SECRET_FILES" = "true" ]; then
        for secret_dir in "$SECRETS_SOURCE_DIR" "$KEYS_DIR"; do
            local secret_path="${secret_dir}/${file_name}"
            if [ -r "$secret_path" ]; then
                log "Reading $env_name from $secret_path"
                tr -d '\r\n' < "$secret_path"
                return 0
            fi
        done
    fi

    # Fallback to environment variable if set
    local env_value
    env_value=$(printenv "$env_name" 2>/dev/null || true)
    if [ -n "$env_value" ]; then
        printf '%s' "$env_value"
        return 0
    fi

    # Final fallback to copied key directory if not already used
    local key_path="${KEYS_DIR}/${file_name}"
    if [ -r "$key_path" ]; then
        log "Using fallback secret file for $env_name at $key_path"
        tr -d '\r\n' < "$key_path"
        return 0
    fi

    log "ERROR: secret for $env_name not found (checked $SECRETS_SOURCE_DIR and $KEYS_DIR)"
    exit 1
}

# Ensure required env vars exist (populated via docker-compose)
require_env APP_DB_USER
require_env APP_DB_RO_USER
require_env TEMPORAL_DB_USER

APP_USER_PASSWORD=$(read_secret_value POSTGRES_APP_USER_PW postgres_app_user_pw)
APP_RO_PASSWORD=$(read_secret_value POSTGRES_APP_RO_PW postgres_app_ro_pw)
TEMPORAL_PASSWORD=$(read_secret_value POSTGRES_TEMPORAL_PW postgres_temporal_pw)
SUPERUSER_PASSWORD=$(read_secret_value POSTGRES_PASSWORD postgres_password)

log "Synchronizing Postgres role passwords with secrets..."

PSQL_CMD=(psql -h 127.0.0.1 -U postgres -v ON_ERROR_STOP=1)
if [ -n "$SUPERUSER_PASSWORD" ]; then
    export PGPASSWORD="${SUPERUSER_PASSWORD}"
    if echo "SELECT 1" | "${PSQL_CMD[@]}" -d postgres >/dev/null 2>&1; then
        log "Connected via password authentication"
    else
        log "Password authentication failed; attempting local peer auth as postgres user"
        unset PGPASSWORD
        PSQL_CMD=(psql -U postgres -v ON_ERROR_STOP=1)
        if [ "$(id -un)" != "postgres" ]; then
            log "ERROR: peer authentication fallback requires running as postgres user"
            exit 1
        fi
    fi
else
    PSQL_CMD=(psql -U postgres -v ON_ERROR_STOP=1)
    if [ "$(id -un)" != "postgres" ]; then
        log "ERROR: peer authentication requires running as postgres user"
        exit 1
    fi
fi

"${PSQL_CMD[@]}" \
  -d postgres \
  -v APP_USER="${APP_DB_USER}" \
  -v APP_RO_USER="${APP_DB_RO_USER}" \
  -v TEMPORAL_USER="${TEMPORAL_DB_USER}" \
  -v APP_USER_PASSWORD="${APP_USER_PASSWORD}" \
  -v APP_RO_USER_PASSWORD="${APP_RO_PASSWORD}" \
  -v TEMPORAL_USER_PASSWORD="${TEMPORAL_PASSWORD}" \
  -v SUPERUSER_PASSWORD="${SUPERUSER_PASSWORD}" <<'SQL'
\set ON_ERROR_STOP on

-- Sync postgres superuser password (used for TCP/IP connections per pg_hba.conf)
SELECT format('ALTER ROLE postgres WITH PASSWORD %L', :'SUPERUSER_PASSWORD')
\gexec

SELECT format('ALTER ROLE %I WITH PASSWORD %L', :'APP_USER', :'APP_USER_PASSWORD')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'APP_USER')
\gexec

SELECT format('ALTER ROLE %I WITH PASSWORD %L', :'APP_RO_USER', :'APP_RO_USER_PASSWORD')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'APP_RO_USER')
\gexec

SELECT format('ALTER ROLE %I WITH PASSWORD %L', :'TEMPORAL_USER', :'TEMPORAL_USER_PASSWORD')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'TEMPORAL_USER')
\gexec
SQL

log "Password synchronization complete."
