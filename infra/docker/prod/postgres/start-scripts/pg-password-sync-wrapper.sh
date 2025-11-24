#!/usr/bin/env bash
set -euo pipefail

log() {
    printf '[pg-password-sync-wrapper] %s\n' "$1" >&2
}

log "Starting Postgres with password sync on startup..."

# Start postgres in background with custom config
POSTGRES_ARGS="${POSTGRES_ARGS:--c config_file=/etc/postgresql/postgresql.conf -c hba_file=/etc/postgresql/pg_hba.conf}"
/usr/local/bin/docker-entrypoint.sh postgres $POSTGRES_ARGS &
POSTGRES_PID=$!

log "Postgres starting with PID $POSTGRES_PID"

# Wait for postgres to be ready
MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if pg_isready -U postgres -h 127.0.0.1 >/dev/null 2>&1; then
        log "Postgres is ready"
        break
    fi
    sleep 1
    WAITED=$((WAITED + 1))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    log "ERROR: Postgres failed to become ready within ${MAX_WAIT} seconds"
    kill $POSTGRES_PID 2>/dev/null || true
    exit 1
fi

# Run password sync script (it will connect as postgres user via password or peer auth)
log "Running password sync script..."
if /opt/entry/admin-scripts/sync-passwords.sh; then
    log "Password sync completed successfully"
else
    log "ERROR: Password sync failed"
    kill $POSTGRES_PID 2>/dev/null || true
    exit 1
fi

log "Startup complete. Postgres running with PID $POSTGRES_PID"

# Wait for postgres process
wait $POSTGRES_PID
