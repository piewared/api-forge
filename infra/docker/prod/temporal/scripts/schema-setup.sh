#!/usr/bin/env sh
set -euo pipefail

# ---- Required env ----
: "${TEMPORAL_DB:?missing DB (database name, e.g. temporal)}"
: "${TEMPORAL_VIS_DB:?missing DB (database name, e.g. temporal_visibility)}"
: "${TEMPORAL_DB_USER:?missing PG_USER (e.g. temporal_user)}"
: "${PW_FILE:?missing PW_FILE (password file for temporal user)}"
: "${EP:?missing EP (Postgres host, e.g. postgres)}"


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
SSL_MODE="${SSL_MODE:-verify-ca}"                         # or 'require' / 'verify-full'
TLS_ENABLE="${TLS_ENABLE:-true}"
TLS_CA_FILE="${TLS_CA_FILE:-/run/secrets/postgres_server_ca}"
TLS_SERVER_NAME="${TLS_SERVER_NAME:-postgres}"  # MUST match a SAN in the server cert

export PGSSLMODE="${SSL_MODE:-verify-ca}"

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
