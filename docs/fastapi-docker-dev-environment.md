# FastAPI Docker Development Environment

Learn how to set up and use the complete FastAPI Docker development environment included with API Forge. This guide covers the local Docker Compose stack with PostgreSQL, Redis, Temporal, and Keycloak, providing a production-like development experience for your FastAPI application.

## Overview

API Forge includes a fully containerized development environment that runs all required services locally using Docker Compose. This FastAPI development setup includes:

- **PostgreSQL 16** - Production-grade database (port 5433)
- **Redis 7** - Caching and session storage (port 6380)
- **Temporal Server** - Workflow orchestration (port 7233)
- **Temporal Web UI** - Workflow monitoring dashboard (port 8082)
- **Keycloak** - OIDC authentication server (port 8080)
- **Pre-configured test users** - Ready-to-use authentication

All services are automatically configured and networked together, with different ports from production to allow running both environments simultaneously.

## Quick Start

Start the entire development environment with one command:

```bash
# Start all services
uv run api-forge-cli deploy up dev

# Wait 30-60 seconds for services to initialize

# Check service status
uv run api-forge-cli deploy status dev

# Start your FastAPI application
uvicorn main:app --reload
```

Your FastAPI application will be available at http://localhost:8000 with automatic reload on code changes.

## CLI Commands

API Forge provides convenient CLI commands for managing the Docker development environment:

### Start Environment

```bash
uv run api-forge-cli deploy up dev
```

Starts all Docker services defined in `docker-compose.dev.yml`:
- Creates Docker network `dev-network`
- Starts PostgreSQL with dev database
- Starts Redis with dev configuration
- Starts Temporal server and Web UI
- Starts Keycloak with test realm and users
- Waits for services to become healthy

### Stop Environment

```bash
uv run api-forge-cli deploy down dev
```

Stops all running services but **preserves data volumes**. Data in PostgreSQL and Redis is retained for the next start.

### Check Status

```bash
uv run api-forge-cli deploy status dev
```

Shows the current status of all development services:

```
Development Environment Status:
✓ Keycloak: Running (Healthy)
✓ PostgreSQL: Running (Healthy)
✓ Redis: Running (Healthy)
✓ Temporal: Running (Healthy)
✓ Temporal UI: Running (Healthy)
```

### View Logs

```bash
# View logs for specific service (using docker-compose directly)
docker-compose -f docker-compose.dev.yml logs postgres
docker-compose -f docker-compose.dev.yml logs redis
docker-compose -f docker-compose.dev.yml logs keycloak
docker-compose -f docker-compose.dev.yml logs temporal

# Follow logs (real-time)
docker-compose -f docker-compose.dev.yml logs -f postgres
```

### Start FastAPI Server

```bash
uvicorn main:app --reload
```

Starts your FastAPI application with:
- Auto-reload on code changes
- Connection to development PostgreSQL (port 5433)
- Connection to development Redis (port 6380)
- Connection to development Temporal (port 7233)
- Development OIDC configuration with Keycloak

## Service Details

### PostgreSQL (port 5433)

**Purpose**: Primary database for development

**Configuration**:
- Host: `localhost` (or `postgres` from within Docker)
- Port: `5433` (different from production's 5432)
- Database: `appdb`
- User: `devuser`
- Password: `devpass`
- Version: PostgreSQL 16

**Connection String**:
```
postgresql://devuser:devpass@localhost:5433/appdb
```

**Direct Access**:
```bash
# Using docker exec
docker exec -it api-forge-postgres-dev psql -U devuser -d appdb

# Using psql directly
psql -h localhost -p 5433 -U devuser -d appdb
```

**Data Persistence**:
Data is stored in Docker volume `postgres_data_dev`. To reset the database:

```bash
uv run api-forge-cli deploy down dev
docker volume rm api-forge-postgres-data-dev
uv run api-forge-cli deploy up dev
```

### Redis (port 6380)

**Purpose**: Session storage, caching, and rate limiting

**Configuration**:
- Host: `localhost` (or `redis` from within Docker)
- Port: `6380` (different from production's 6379)
- Password: `devredispass`
- Version: Redis 7

**Connection String**:
```
redis://:devredispass@localhost:6380/0
```

**Direct Access**:
```bash
# Using docker exec
docker exec -it api-forge-redis-dev redis-cli -a devredispass

# Example commands in redis-cli
> KEYS *                    # List all keys
> GET session:sess_abc123   # Get session data
> TTL session:sess_abc123   # Check expiration
> FLUSHDB                   # Clear all data (use carefully!)
```

**Data Persistence**:
Data is stored in Docker volume `redis_data_dev`.

### Temporal (port 7233, 8082)

**Purpose**: Distributed workflow orchestration

**Configuration**:
- Server: `localhost:7233` (gRPC endpoint)
- Web UI: `http://localhost:8082`
- Namespace: `default`
- Version: Temporal 1.29.0

**Web UI Features**:
- View all workflows and activities
- Inspect workflow execution history
- Search workflows by status or ID
- Monitor task queues
- View worker status

**Direct Access**:
```bash
# Using temporal CLI (if installed)
temporal workflow list --namespace default

# View workflow details
temporal workflow describe --workflow-id my-workflow-id
```

### Keycloak (port 8080)

**Purpose**: Local OIDC authentication provider for testing

**Configuration**:
- URL: `http://localhost:8080`
- Admin Console: `http://localhost:8080/admin`
- Admin User: `admin` / `admin`
- Realm: `test-realm`
- Client ID: `test-client`
- Client Secret: `test-client-secret`

**Pre-configured Test Users**:

1. **testuser1**
   - Email: `testuser1@example.com`
   - Password: `password123`
   - Name: Test User One

2. **testuser2**
   - Email: `testuser2@example.com`
   - Password: `password123`
   - Name: Test User Two

**Testing Authentication**:
```bash
# Login with Keycloak
curl -X GET 'http://localhost:8000/auth/web/login?provider=keycloak'

# Or visit in browser
open http://localhost:8000/auth/web/login?provider=keycloak
```

**Keycloak Setup Script**:
The Keycloak service runs an automatic setup script (`src/dev/setup_keycloak.py`) that:
- Creates the `test-realm`
- Configures the `test-client` with correct redirect URIs
- Creates test users with verified emails
- Is idempotent (safe to run multiple times)

## Environment Variables

The development environment uses these environment variables (from `.env`):

```bash
# Application
APP_ENVIRONMENT=development
APP_NAME=My API

# Database (development)
DATABASE_URL=postgresql://devuser:devpass@localhost:5433/appdb

# Redis (development)
REDIS_URL=redis://:devredispass@localhost:6380/0

# Temporal
TEMPORAL_URL=localhost:7233
TEMPORAL_NAMESPACE=default

# Keycloak (development only)
KEYCLOAK_ENABLED=true
KEYCLOAK_ISSUER=http://localhost:8080/realms/test-realm
OIDC_KEYCLOAK_CLIENT_ID=test-client
OIDC_KEYCLOAK_CLIENT_SECRET=test-client-secret

# Session secrets (CHANGE IN PRODUCTION!)
SESSION_SIGNING_SECRET=dev-session-secret-change-in-production
CSRF_SIGNING_SECRET=dev-csrf-secret-change-in-production
```

## Development Workflow

### Typical Development Session

1. **Start services** (one time per day/session):
   ```bash
   uv run api-forge-cli deploy up dev
   ```

2. **Wait for services to be ready** (30-60 seconds):
   ```bash
   uv run api-forge-cli deploy status dev
   ```

3. **Initialize database** (first time only):
   ```bash
   uv run api-forge-init-db
   ```

4. **Start FastAPI application**:
   ```bash
   uvicorn main:app --reload
   ```

5. **Make code changes** - FastAPI auto-reloads

6. **Test authentication**:
   - Visit http://localhost:8000/docs
   - Click "Login with Keycloak"
   - Use `testuser1@example.com` / `password123`

7. **View Temporal workflows**:
   - Visit http://localhost:8082

8. **Run tests**:
   ```bash
   # Unit tests
   uv run pytest tests/unit/
   
   # Integration tests (need dev environment)
   uv run pytest tests/integration/
   ```

9. **Stop services** (end of day):
   ```bash
   uv run api-forge-cli deploy down dev
   ```

### Database Migrations

When you change SQLModel models:

```bash
# Re-initialize database (WARNING: drops all data)
uv run api-forge-init-db

# Or manually create tables
uv run python -c "
from src.app.runtime.config import get_config
from src.app.core.database import init_db
config = get_config()
init_db(config.database.connection_string)
"
```

For production-grade migrations, consider adding Alembic to your project.

### Debugging Services

**PostgreSQL Connection Issues**:
```bash
# Check if PostgreSQL is running
docker ps | grep postgres

# Check PostgreSQL logs
docker-compose -f docker-compose.dev.yml logs postgres

# Verify port is listening
netstat -an | grep 5433

# Test connection
psql -h localhost -p 5433 -U devuser -d appdb -c "SELECT version();"
```

**Redis Connection Issues**:
```bash
# Check if Redis is running
docker ps | grep redis

# Check Redis logs
docker-compose -f docker-compose.dev.yml logs redis

# Test connection
docker exec -it api-forge-redis-dev redis-cli -a devredispass ping
# Should respond: PONG
```

**Temporal Connection Issues**:
```bash
# Check if Temporal is running
docker ps | grep temporal

# Check Temporal logs
docker-compose -f docker-compose.dev.yml logs temporal

# Access Web UI
open http://localhost:8082
```

**Keycloak Issues**:
```bash
# Check Keycloak logs
docker-compose -f docker-compose.dev.yml logs keycloak

# Verify realm exists
curl http://localhost:8080/realms/test-realm/.well-known/openid-configuration

# Access admin console
open http://localhost:8080/admin
# Login: admin / admin
```

## Port Conflicts

If you see "port already in use" errors, another service is using the development ports:

**Check what's using a port**:
```bash
# On Linux
sudo netstat -tlnp | grep :8080

# On macOS
lsof -i :8080
```

**Common conflicts**:
- **5433**: Another PostgreSQL instance
- **6380**: Another Redis instance
- **7233**: Another Temporal server
- **8080**: Another web server or Keycloak
- **8082**: Another Temporal UI

**Solutions**:
1. Stop the conflicting service
2. Change ports in `docker-compose.dev.yml`
3. Update corresponding environment variables

## Data Management

### Resetting All Data

To start fresh with empty databases:

```bash
# Stop services
uv run api-forge-cli deploy down dev

# Remove volumes
docker volume rm api-forge-postgres-data-dev
docker volume rm api-forge-redis-data-dev
docker volume rm api-forge-temporal-data-dev

# Start services
uv run api-forge-cli deploy up dev

# Re-initialize database
uv run api-forge-init-db
```

### Backing Up Development Data

```bash
# Backup PostgreSQL
docker exec api-forge-postgres-dev pg_dump -U devuser appdb > backup.sql

# Restore PostgreSQL
docker exec -i api-forge-postgres-dev psql -U devuser appdb < backup.sql

# Backup Redis (saves RDB snapshot)
docker exec api-forge-redis-dev redis-cli -a devredispass SAVE
docker cp api-forge-redis-dev:/data/dump.rdb redis-backup.rdb
```

## Differences from Production

The development environment intentionally differs from production:

| Feature | Development | Production |
|---------|-------------|------------|
| PostgreSQL Port | 5433 | 5432 |
| Redis Port | 6380 | 6379 |
| Database User | devuser | appuser |
| Passwords | Hardcoded | From secrets |
| TLS/SSL | Disabled | Required |
| Keycloak | Included | External provider |
| Session Secret | Hardcoded | Random generated |
| Cookie Secure Flag | False | True |
| Docker Network | dev-network | App-specific |

These differences allow running both environments simultaneously and make local development easier.

## Docker Compose Configuration

The development environment is defined in `docker-compose.dev.yml`:

```yaml
services:
  postgres:
    image: postgres:16
    container_name: api-forge-postgres-dev
    ports:
      - "5433:5432"
    environment:
      POSTGRES_USER: devuser
      POSTGRES_PASSWORD: devpass
      POSTGRES_DB: appdb
    volumes:
      - postgres_data_dev:/var/lib/postgresql/data
    networks:
      - dev-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U devuser"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7
    container_name: api-forge-redis-dev
    ports:
      - "6380:6379"
    command: redis-server --requirepass devredispass
    volumes:
      - redis_data_dev:/data
    networks:
      - dev-network
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "devredispass", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  temporal:
    image: temporalio/auto-setup:1.29.0
    container_name: api-forge-temporal-dev
    ports:
      - "7233:7233"
    environment:
      - DB=postgresql
      - DB_PORT=5432
      - POSTGRES_USER=devuser
      - POSTGRES_PWD=devpass
      - POSTGRES_SEEDS=postgres
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - dev-network

  temporal-ui:
    image: temporalio/ui:latest
    container_name: api-forge-temporal-ui-dev
    ports:
      - "8082:8080"
    environment:
      - TEMPORAL_ADDRESS=temporal:7233
    depends_on:
      - temporal
    networks:
      - dev-network

  keycloak:
    image: quay.io/keycloak/keycloak:latest
    container_name: api-forge-keycloak-dev
    ports:
      - "8080:8080"
    environment:
      - KEYCLOAK_ADMIN=admin
      - KEYCLOAK_ADMIN_PASSWORD=admin
    command: start-dev
    networks:
      - dev-network

volumes:
  postgres_data_dev:
  redis_data_dev:
  temporal_data_dev:

networks:
  dev-network:
    driver: bridge
```

## Customizing the Environment

You can customize the development environment by editing `docker-compose.dev.yml`:

**Change PostgreSQL version**:
```yaml
postgres:
  image: postgres:15  # Change from 16
```

**Add pgAdmin**:
```yaml
pgadmin:
  image: dpage/pgadmin4
  ports:
    - "5050:80"
  environment:
    PGADMIN_DEFAULT_EMAIL: admin@example.com
    PGADMIN_DEFAULT_PASSWORD: admin
  networks:
    - dev-network
```

**Add Redis Commander**:
```yaml
redis-commander:
  image: rediscommander/redis-commander
  ports:
    - "8081:8081"
  environment:
    - REDIS_HOSTS=redis:redis:6379:0:devredispass
  networks:
    - dev-network
```

## Troubleshooting

### Services Won't Start

**Check Docker is running**:
```bash
docker ps
```

**Check for existing containers**:
```bash
docker ps -a | grep api-forge
# Remove old containers if needed
docker rm api-forge-postgres-dev api-forge-redis-dev
```

**Check disk space**:
```bash
docker system df
# Clean up if needed
docker system prune
```

### FastAPI Can't Connect to Services

**Verify services are healthy**:
```bash
uv run api-forge-cli deploy status dev
```

**Check environment variables**:
```bash
cat .env | grep -E "DATABASE_URL|REDIS_URL|TEMPORAL_URL"
```

**Test connectivity from host**:
```bash
# PostgreSQL
psql -h localhost -p 5433 -U devuser -d appdb -c "SELECT 1;"

# Redis
redis-cli -h localhost -p 6380 -a devredispass PING

# Temporal (requires grpcurl)
grpcurl -plaintext localhost:7233 list
```

### Performance Issues

**Docker resource limits**:
- Increase Docker Desktop memory (Preferences > Resources)
- Recommended: 4GB+ RAM for all services

**Volume performance on macOS**:
- Consider using Docker named volumes instead of bind mounts
- Use `:delegated` or `:cached` for bind mounts

## Related Documentation

- [FastAPI Authentication with OIDC](./fastapi-auth-oidc-bff.md) - Using Keycloak for authentication
- [FastAPI Testing Strategy](./fastapi-testing-strategy.md) - Running integration tests
- [FastAPI Temporal Workflows](./fastapi-temporal-workflows.md) - Using Temporal in development

## Additional Resources

- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [PostgreSQL Docker Image](https://hub.docker.com/_/postgres)
- [Redis Docker Image](https://hub.docker.com/_/redis)
- [Temporal Documentation](https://docs.temporal.io/)
- [Keycloak Documentation](https://www.keycloak.org/documentation)
