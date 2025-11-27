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

# Call Temporal's original entrypoint
exec /etc/temporal/entrypoint.sh "$@"