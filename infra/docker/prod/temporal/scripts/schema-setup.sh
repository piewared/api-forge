#!/usr/bin/env sh
set -euo pipefail

# ---- Required env ----
: "${TEMPORAL_DB:?missing TEMPORAL_DB (database name, e.g. temporal)}"
: "${TEMPORAL_VIS_DB:?missing TEMPORAL_VIS_DB (database name, e.g. temporal_visibility)}"
: "${TEMPORAL_DB_USER:?missing TEMPORAL_DB_USER (e.g. temporal_user)}"
: "${PW_FILE:?missing PW_FILE (password file for temporal user)}"

# ---- Parse EP (postgres host) from PRODUCTION_DATABASE_URL if not set ----
# Supports:
#   - postgresql://host:port/db?options (no credentials)
#   - postgresql://host:port?options (no credentials, no db)
#   - postgresql://user:pass@host:port/db?options (with credentials)
if [ -z "${EP:-}" ] && [ -n "${PRODUCTION_DATABASE_URL:-}" ]; then
    echo "Parsing database host from PRODUCTION_DATABASE_URL..."
    
    # Check if URL contains @ (has credentials)
    if echo "$PRODUCTION_DATABASE_URL" | grep -q '@'; then
        # Format: postgresql://user:pass@host:port/db
        HOST_PORT=$(echo "$PRODUCTION_DATABASE_URL" | sed -E 's|.*@([^/?]+).*|\1|')
    else
        # Format: postgresql://host:port/db or postgresql://host:port?options
        # Remove scheme (postgresql://) and everything after / or ?
        HOST_PORT=$(echo "$PRODUCTION_DATABASE_URL" | sed -E 's|^[^:]+://([^/?]+).*|\1|')
    fi
    
    # Extract just host (before :)
    EP=$(echo "$HOST_PORT" | sed -E 's|:.*||')
    # Extract port if present (after :), default to 5432
    PARSED_PORT=$(echo "$HOST_PORT" | grep -oE ':[0-9]+' | tr -d ':' || echo "")
    if [ -n "$PARSED_PORT" ]; then
        PG_PORT="$PARSED_PORT"
    fi
    # Also set TLS_SERVER_NAME to match the actual host
    if [ -z "${TLS_SERVER_NAME:-}" ]; then
        TLS_SERVER_NAME="$EP"
    fi
    echo "Parsed from URL: EP=$EP, PG_PORT=${PG_PORT:-5432}, TLS_SERVER_NAME=$TLS_SERVER_NAME"
fi

# Validate EP is set
: "${EP:?missing EP (set EP directly or provide PRODUCTION_DATABASE_URL)}"

# Optional env
PG_PORT="${PG_PORT:-5432}"
PLUGIN="${PLUGIN:-postgres12}"    # postgres12 for PG >= 12, use postgres for older

# Read password securely from Docker secret
echo "Reading password from $PW_FILE..."
if [ ! -f "$PW_FILE" ]; then
    echo "ERROR: Password file $PW_FILE does not exist!"
    exit 1
fi
PGPASSWORD="$(cat "$PW_FILE")"
export PGPASSWORD
echo "Password loaded successfully."


# TLS (defaults; override via env if needed)
SSL_MODE="${SSL_MODE:-verify-ca}"
TLS_ENABLE="${TLS_ENABLE:-true}"
TLS_CA_FILE="${TLS_CA_FILE:-/run/secrets/postgres_server_ca}"
TLS_SERVER_NAME="${TLS_SERVER_NAME:-postgres}"  # MUST match a SAN in the server cert

export PGSSLMODE="${SSL_MODE}"

# Verify TLS CA file exists if TLS is enabled
if [ "$TLS_ENABLE" = "true" ]; then
    echo "TLS enabled with mode: $SSL_MODE"
    echo "Checking TLS CA file: $TLS_CA_FILE"
    if [ ! -f "$TLS_CA_FILE" ]; then
        echo "ERROR: TLS CA file $TLS_CA_FILE does not exist!"
        echo "Either provide the CA file or set TLS_ENABLE=false"
        exit 1
    fi
    echo "TLS CA file found."
else
    echo "TLS disabled (TLS_ENABLE=$TLS_ENABLE)"
fi

# Helper wrapper
run_sql_tool () {
  local DB="$1"   # temporal | temporal_visibility
  local action="$2"          # setup-schema ... | update-schema ...

  echo "==========================================="
  echo "Running temporal-sql-tool:"
  echo "  DB: $DB"
  echo "  Action: $action"
  echo "  Host: $EP:$PG_PORT"
  echo "  User: $TEMPORAL_DB_USER"
  echo "  Plugin: $PLUGIN"
  echo "  TLS: $TLS_ENABLE"
  if [ "$TLS_ENABLE" = "true" ]; then
    echo "  TLS CA: $TLS_CA_FILE"
    echo "  TLS Server Name: $TLS_SERVER_NAME"
    echo "  SSL Mode: $SSL_MODE"
  fi
  echo "==========================================="

  if ! temporal-sql-tool \
    --plugin "$PLUGIN" \
    --ep "$EP" -p "$PG_PORT" \
    -u "$TEMPORAL_DB_USER" -pw "$PGPASSWORD" \
    --db "$DB" \
    --tls="$TLS_ENABLE" \
    --tls-ca-file "$TLS_CA_FILE" \
    --tls-server-name "$TLS_SERVER_NAME" \
    $action; then
    echo "ERROR: temporal-sql-tool failed for database '$DB' with action '$action'"
    echo "Check the error message above for details."
    return 1
  fi
  
  echo "SUCCESS: temporal-sql-tool completed for $DB"
}
echo "== Temporal schema setup =="
echo "Main schema=$TEMPORAL_DB, Visibility schema=$TEMPORAL_VIS_DB"

# --- Main store ---
echo "--> Creating/updating main store in schema: $TEMPORAL_DB"
run_sql_tool "$TEMPORAL_DB" "setup-schema -v 0.0" || true
run_sql_tool "$TEMPORAL_DB" "update-schema --schema-name postgresql/v12/temporal"

# --- Visibility store ---
echo "--> Creating/updating visibility store in schema: $TEMPORAL_VIS_DB"
run_sql_tool "$TEMPORAL_VIS_DB" "setup-schema -v 0.0" || true
run_sql_tool "$TEMPORAL_VIS_DB" "update-schema --schema-name postgresql/v12/visibility"


echo "== Temporal schema setup complete =="
