#!/bin/bash

# Development environment setup script
# Prefer the CLI as the source of truth, fall back to direct docker compose.

set -e

DEV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$DEV_DIR")"

if command -v uv >/dev/null 2>&1; then
    echo "🚀 Using API Forge CLI to start dev environment..."
    (cd "$PROJECT_ROOT" && uv run api-forge-cli dev up --no-start-server)
    exit 0
fi

echo "⚠️  uv not found; falling back to docker compose setup"

echo "🚀 Setting up development environment..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

# Start development services
echo "📦 Starting development services..."
cd "$DEV_DIR"
docker compose up -d

# Wait for Keycloak to be ready
echo "⏳ Waiting for Keycloak to be ready..."
timeout=300
counter=0

while ! curl -sf http://localhost:8080/realms/master > /dev/null 2>&1; do
    if [ $counter -ge $timeout ]; then
        echo "❌ Timeout waiting for Keycloak to start"
        exit 1
    fi
    echo "Waiting for Keycloak... ($counter/${timeout}s)"
    sleep 5
    counter=$((counter + 5))
done

echo "✅ Keycloak is ready!"

# Configure Keycloak realm and client
echo "⚙️  Configuring Keycloak realm and client..."
python3 "$DEV_DIR/setup_keycloak.py"

echo ""
echo "🎉 Development environment ready!"
echo ""
echo "Services:"
echo "  Keycloak Admin: http://localhost:8080 (admin/admin)"
echo "  PostgreSQL: localhost:5432 (appuser/devpass)"
echo ""
echo "Databases:"
echo "  Development: postgresql://appuser:devpass@localhost:5432/appdb"
echo "  Test: postgresql://appuser:devpass@localhost:5432/testdb"
echo ""
echo "Test Realm: test-realm"
echo "Test Client: test-client"
echo "Test Users:"
echo "  - testuser1@example.com / password123"
echo "  - testuser2@example.com / password123"
echo ""
echo "To stop the environment:"
echo "  cd dev_env && docker compose down"
echo ""
