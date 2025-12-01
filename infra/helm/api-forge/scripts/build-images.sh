#!/usr/bin/env bash
set -euo pipefail

echo "Building images..."
# Use Docker Compose v2 (docker compose) instead of v1 (docker-compose)
docker compose -f docker-compose.prod.yml build
