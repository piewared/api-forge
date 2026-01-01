#!/bin/bash

# Development environment cleanup script
# Stops containers and optionally removes data volumes.

set -e

DEV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🧹 Cleaning up development environment..."

cd "$DEV_DIR"

# Stop and remove containers
echo "🛑 Stopping containers..."
docker compose down

# Remove volumes (optional)
if [ "$1" = "--remove-data" ]; then
    echo "🗑️  Removing persistent data volumes..."
    docker compose down -v
    docker volume rm dev-env_keycloak_data dev-env_postgres_data 2>/dev/null || true
fi

echo "✅ Development environment cleaned up!"
echo ""
echo "To restart the environment:"
echo "  ./setup_dev.sh"
