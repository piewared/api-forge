#!/bin/sh
set -e

# Temporal server expects POSTGRES_PWD environment variable
# The universal-entrypoint creates POSTGRES_TEMPORAL_PW from the secret file
# This script sets POSTGRES_PWD from that auto-created variable

if [ -n "$POSTGRES_TEMPORAL_PW" ]; then
    export POSTGRES_PWD="$POSTGRES_TEMPORAL_PW"
    echo "✓ Set POSTGRES_PWD from POSTGRES_TEMPORAL_PW"
else
    echo "❌ ERROR: POSTGRES_TEMPORAL_PW not set" >&2
    echo "   Universal entrypoint should have created this from postgres_temporal_pw secret" >&2
    exit 1
fi

# Parse POSTGRES_SEEDS, SQL_HOST_NAME, and DB_PORT from PRODUCTION_DATABASE_URL if not set
# Supports:
#   - postgresql://host:port/db?options (no credentials)
#   - postgresql://host:port?options (no credentials, no db)
#   - postgresql://user:pass@host:port/db?options (with credentials)
if [ -z "${POSTGRES_SEEDS:-}" ] && [ -n "${PRODUCTION_DATABASE_URL:-}" ]; then
    echo "Parsing database connection from PRODUCTION_DATABASE_URL..."
    
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
    PG_HOST=$(echo "$HOST_PORT" | sed -E 's|:.*||')
    # Extract port if present (after :), default to 5432
    PARSED_PORT=$(echo "$HOST_PORT" | grep -oE ':[0-9]+' | tr -d ':' || echo "")
    
    export POSTGRES_SEEDS="$PG_HOST"
    echo "✓ Set POSTGRES_SEEDS=$POSTGRES_SEEDS from URL"
    
    # Set SQL_HOST_NAME if not set (for TLS verification)
    if [ -z "${SQL_HOST_NAME:-}" ]; then
        export SQL_HOST_NAME="$PG_HOST"
        echo "✓ Set SQL_HOST_NAME=$SQL_HOST_NAME from URL"
    fi
    
    # Set DB_PORT if parsed from URL
    if [ -n "$PARSED_PORT" ]; then
        export DB_PORT="$PARSED_PORT"
        echo "✓ Set DB_PORT=$DB_PORT from URL"
    fi
fi

# Validate POSTGRES_SEEDS is set
if [ -z "${POSTGRES_SEEDS:-}" ]; then
    echo "❌ ERROR: POSTGRES_SEEDS not set" >&2
    echo "   Set PG_HOST in .env or provide PRODUCTION_DATABASE_URL" >&2
    exit 1
fi

# Call Temporal's original entrypoint
exec /etc/temporal/entrypoint.sh "$@"