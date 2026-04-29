# PostgreSQL Configuration Guide

## Overview

This guide covers all PostgreSQL configuration options, environment variables, and connection string formats used in the application.

## Configuration Files

### 1. Application Config (`config.yaml`)

Location: `/config.yaml`

```yaml
database:
  # Connection URL with environment variable substitution
  url: "${DATABASE_URL:-postgresql+asyncpg://user:password@postgres:5432/app_db}"
  
  # Database and user names
  app_db: "${APP_DB:-appdb}"
  owner_user: "${APP_DB_OWNER:-appowner}"
  user: "${APP_DB_USER:-appuser}"
  ro_user: "${APP_DB_RO_USER:-backupuser}"
  
  # Connection pool settings
  pool_size: 20              # Base pool size
  max_overflow: 10           # Additional connections beyond base
  pool_timeout: 30           # Wait time for available connection (seconds)
  pool_recycle: 1800         # Recycle connections after 30 minutes
  
  # Environment mode
  environment_mode: "${APP_ENVIRONMENT:-development}"
  
  # Password sources (production)
  user_pw_file_path: "${DATABASE_PASSWORD_FILE_PATH:-/run/secrets/postgres_app_user_pw}"
  user_pw_env_var: "${DATABASE_PASSWORD_ENV_VAR:-POSTGRES_APP_USER_PW}"
```

### 2. Environment Variables (`.env`)

Create from template:
```bash
cp .env.example .env
```

**Required Variables:**

```bash
# Environment mode (development, production, testing)
APP_ENVIRONMENT=development

# Database connection string
# Development (PostgreSQL)
DATABASE_URL=postgresql://appuser:devpass@localhost:5433/appdb

# Production (PostgreSQL with SSL)
DATABASE_URL=postgresql://appuser:${POSTGRES_APP_USER_PW}@postgres:5432/appdb?sslmode=require

# Alternative: SQLite (development only)
DATABASE_URL=sqlite:///./database.db

# Database names and users
APP_DB=appdb
APP_DB_OWNER=appowner
APP_DB_USER=appuser
APP_DB_RO_USER=backupuser

# Temporal databases
TEMPORAL_DB=temporal
TEMPORAL_VIS_DB=temporal_visibility
TEMPORAL_DB_USER=temporaluser
```

**Production-Only Variables:**

```bash
# Password file paths (Docker secrets)
DATABASE_PASSWORD_FILE_PATH=/run/secrets/postgres_app_user_pw
POSTGRES_APP_USER_PW=/run/secrets/postgres_app_user_pw
POSTGRES_APP_RO_PW=/run/secrets/postgres_app_ro_pw
POSTGRES_TEMPORAL_PW=/run/secrets/postgres_temporal_pw
```

### 3. PostgreSQL Server Config (`postgresql.conf`)

Location: `/infra/docker/prod/postgres/postgresql.conf`

**Connection Settings:**
```properties
listen_addresses = '*'
port = 5432
max_connections = 100
superuser_reserved_connections = 3
```

**Memory Settings:**
```properties
shared_buffers = 256MB          # ~25% of available RAM
work_mem = 4MB                  # Per-operation memory
maintenance_work_mem = 64MB     # For VACUUM, CREATE INDEX
effective_cache_size = 1GB      # Total system cache estimate
```

**Write Ahead Logging (WAL):**
```properties
wal_level = replica             # Enable replication
max_wal_size = 1GB
min_wal_size = 80MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
```

**Performance Tuning:**
```properties
random_page_cost = 1.1          # SSD optimization (default: 4.0)
effective_io_concurrency = 200  # SSD parallel I/O
```

**Security Settings:**
```properties
ssl = on
ssl_cert_file = '/etc/postgresql/ssl/server.crt'
ssl_key_file = '/etc/postgresql/ssl/server.key'
ssl_prefer_server_ciphers = on
ssl_ciphers = 'HIGH:!aNULL:!MD5'
ssl_min_protocol_version = 'TLSv1.2'
ssl_max_protocol_version = 'TLSv1.3'
password_encryption = scram-sha-256
row_security = on
```

**Logging:**
```properties
log_destination = 'stderr'
logging_collector = on
log_directory = 'pg_log'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
log_line_prefix = '%t [%p-%l] %q%u@%d '
log_min_duration_statement = 1000  # Log queries > 1 second
log_connections = on
log_disconnections = on
log_lock_waits = on
```

**Statement Tracking:**
```properties
shared_preload_libraries = 'pg_stat_statements'
track_activities = on
track_counts = on
track_io_timing = on
track_functions = all
```

### 4. Client Authentication (`pg_hba.conf`)

Location: `/infra/docker/prod/postgres/pg_hba.conf`

```properties
# TYPE  DATABASE        USER            ADDRESS                 METHOD

# Unix socket connections
local   all             postgres                                peer
local   all             all                                     scram-sha-256

# Localhost connections
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256

# Replication connections
local   replication     all                                     peer
host    replication     all             127.0.0.1/32            scram-sha-256

# Reject non-TLS connections
hostnossl all           all             0.0.0.0/0               reject
hostnossl all           all             ::/0                    reject

# Allow TLS connections from private networks
hostssl  all            all             172.30.50.0/24          scram-sha-256  # Backend network
hostssl  all            all             172.18.0.0/16           scram-sha-256  # Docker network
hostssl  all            all             10.10.0.0/16            scram-sha-256  # Private network

# Final deny-all (defense in depth)
host     all            all             0.0.0.0/0               reject
host     all            all             ::/0                    reject
```

## Connection Strings

### Format

```
postgresql://[user[:password]@][host][:port][/dbname][?param1=value1&...]
```

### Development Examples

**PostgreSQL (standard):**
```bash
DATABASE_URL=postgresql://appuser:devpass@localhost:5433/appdb
```

**PostgreSQL (with connection pool options):**
```bash
DATABASE_URL=postgresql://appuser:devpass@localhost:5433/appdb?pool_size=10&max_overflow=5
```

**SQLite (development only):**
```bash
DATABASE_URL=sqlite:///./database.db
```

**SQLite (in-memory, testing):**
```bash
DATABASE_URL=sqlite:///:memory:
```

### Production Examples

**PostgreSQL with SSL (required):**
```bash
DATABASE_URL=postgresql://appuser:${POSTGRES_APP_USER_PW}@postgres:5432/appdb?sslmode=require
```

**PostgreSQL with SSL verification:**
```bash
DATABASE_URL=postgresql://appuser:${POSTGRES_APP_USER_PW}@postgres:5432/appdb?sslmode=verify-ca&sslrootcert=/run/secrets/ca-bundle.crt
```

**PostgreSQL with full SSL verification:**
```bash
DATABASE_URL=postgresql://appuser:${POSTGRES_APP_USER_PW}@postgres:5432/appdb?sslmode=verify-full&sslrootcert=/run/secrets/ca-bundle.crt&sslcert=/run/secrets/client.crt&sslkey=/run/secrets/client.key
```

### Connection Parameters

| Parameter | Description | Values | Default |
|-----------|-------------|--------|---------|
| `sslmode` | SSL connection mode | `disable`, `allow`, `prefer`, `require`, `verify-ca`, `verify-full` | `prefer` |
| `sslrootcert` | CA certificate file path | File path | None |
| `sslcert` | Client certificate file path | File path | None |
| `sslkey` | Client private key file path | File path | None |
| `connect_timeout` | Connection timeout (seconds) | Integer | 10 |
| `options` | PostgreSQL server options | String | None |
| `application_name` | Application identifier | String | None |

## Connection Pool Configuration

### Pool Size Calculation

**Formula:**
```
connections_needed = (max_concurrent_requests * avg_query_time) / request_duration
```

**Example:**
- Max concurrent requests: 100
- Average query time: 50ms (0.05s)
- Request duration: 200ms (0.2s)

```
connections_needed = (100 * 0.05) / 0.2 = 25
```

Recommended: `pool_size: 20`, `max_overflow: 10` (total: 30)

### Configuration Options

```yaml
database:
  pool_size: 20              # Persistent connections in pool
  max_overflow: 10           # Temporary connections beyond pool_size
  pool_timeout: 30           # Wait time before timing out (seconds)
  pool_recycle: 1800         # Recycle connections after 30 minutes
```

**Tuning Guidelines:**

| Workload Type | pool_size | max_overflow | pool_timeout |
|---------------|-----------|--------------|--------------|
| Low traffic (< 10 RPS) | 5 | 5 | 30 |
| Medium traffic (10-50 RPS) | 10 | 10 | 30 |
| High traffic (50-200 RPS) | 20 | 10 | 30 |
| Very high traffic (> 200 RPS) | 30 | 20 | 60 |

### Pool Monitoring

The application exposes pool metrics for monitoring:

```python
from src.app.core.services.database.db_session import DbSessionService

db_service = DbSessionService()
status = db_service.get_pool_status()

# Returns:
{
    "size": 20,           # Total pool size
    "checked_in": 18,     # Available connections
    "checked_out": 2,     # In-use connections
    "overflow": 0,        # Overflow connections created
    "invalid": 0          # Failed connections
}
```

## Database Roles and Permissions

### Three-Role Security Pattern

The application uses a least-privilege security model with three roles:

```
┌──────────────────────────────────────────────┐
│  Database Owner: appowner (NOLOGIN)          │
│  - Owns database and schema                  │
│  - Creates tables and objects                │
│  - No connection capability                  │
└──────────────────────────────────────────────┘
              │
              ├─────────────────────────────────┐
              │                                 │
┌─────────────▼──────────────┐  ┌──────────────▼─────────────┐
│  Application User: appuser │  │  Read-Only: backupuser     │
│  (LOGIN)                   │  │  (LOGIN)                   │
│  - SELECT, INSERT, UPDATE, │  │  - SELECT only             │
│    DELETE                  │  │  - Used for backups        │
│  - Runtime operations      │  │  - Reporting/analytics     │
└────────────────────────────┘  └────────────────────────────┘
```

### Role Creation (Production)

Roles are created automatically by init scripts:

**Development:**
```bash
# Hardcoded in docker-compose.dev.yml
POSTGRES_USER=postgres
POSTGRES_PASSWORD=devpass
APP_DB_USER=appuser
APP_DB_USER_PW=devpass
```

**Production:**
```bash
# Created by init-scripts/01-init-app.sh
CREATE ROLE appowner NOLOGIN;
CREATE ROLE appuser LOGIN PASSWORD '${POSTGRES_APP_USER_PW}';
CREATE ROLE backupuser LOGIN PASSWORD '${POSTGRES_APP_RO_PW}';

CREATE DATABASE appdb OWNER appowner;

\connect appdb
CREATE SCHEMA app AUTHORIZATION appowner;

GRANT USAGE ON SCHEMA app TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO appuser;
GRANT SELECT ON ALL TABLES IN SCHEMA app TO backupuser;
```

### Temporal Roles

Temporal uses a similar pattern:

```sql
-- Temporal owner (NOLOGIN)
CREATE ROLE temporaluser_owner NOLOGIN;

-- Temporal runtime user (LOGIN)
CREATE ROLE temporaluser LOGIN PASSWORD '${POSTGRES_TEMPORAL_PW}';

-- Temporal databases
CREATE DATABASE temporal OWNER temporaluser_owner;
CREATE DATABASE temporal_visibility OWNER temporaluser_owner;

-- Grant permissions
\connect temporal
GRANT USAGE, CREATE ON SCHEMA public TO temporaluser;
GRANT ALL ON ALL TABLES IN SCHEMA public TO temporaluser;
```

## Environment-Specific Configuration

### Development Configuration

**Docker Compose:**
```yaml
services:
  postgres:
    container_name: api-forge-postgres-dev
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: devpass
      APP_DB: appdb
      APP_DB_USER: appuser
      APP_DB_USER_PW: devpass
    ports:
      - "5433:5432"  # Non-standard port to avoid conflicts
    volumes:
      - postgres_data_dev:/var/lib/postgresql/data
    networks:
      - dev-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d postgres"]
      interval: 10s
      timeout: 5s
      retries: 5
```

**Connection String:**
```bash
DATABASE_URL=postgresql://appuser:devpass@localhost:5433/appdb
```

**Features:**
- Hardcoded passwords (acceptable for local development)
- Exposed on non-standard port (5433)
- No TLS/SSL required
- Minimal logging
- Single database (appdb)

### Production Configuration

**Docker Compose:**
```yaml
services:
  postgres:
    container_name: api-forge-postgres
    image: postgres:16-alpine
    environment:
      APP_DB: ${APP_DB:-appdb}
      APP_DB_USER: ${APP_DB_USER:-appuser}
      APP_DB_OWNER: ${APP_DB_OWNER:-appowner}
      APP_DB_RO_USER: ${APP_DB_RO_USER:-backupuser}
      POSTGRES_INITDB_ARGS: "--auth-host=scram-sha-256 --data-checksums"
    secrets:
      - postgres_password
      - postgres_app_owner_pw
      - postgres_app_user_pw
      - postgres_app_ro_pw
      - postgres_temporal_pw
      - postgres_tls_cert
      - postgres_tls_key
      - postgres_server_ca
    ports:
      - "127.0.0.1:5432:5432"  # Localhost only
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
      - ./data/postgres-backups:/var/lib/postgresql/backups
      - ./infra/docker/prod/postgres/postgresql.conf:/etc/postgresql/postgresql.conf:ro
      - ./infra/docker/prod/postgres/pg_hba.conf:/etc/postgresql/pg_hba.conf:ro
    networks:
      - backend
```

**Connection String:**
```bash
DATABASE_URL=postgresql://appuser:${POSTGRES_APP_USER_PW}@postgres:5432/appdb?sslmode=require
```

**Features:**
- Docker secrets for passwords
- TLS/SSL required
- Multiple databases (appdb, temporal, temporal_visibility)
- Comprehensive logging
- Backups enabled
- Network isolation (backend network only)

### Testing Configuration

**pytest fixture:**
```python
import pytest
from sqlmodel import Session, create_engine
from sqlmodel.pool import StaticPool

@pytest.fixture(name="db_session")
def db_session_fixture():
    # In-memory SQLite for fast tests
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # Reuse same connection
    )
    
    # Create tables
    SQLModel.metadata.create_all(engine)
    
    with Session(engine) as session:
        yield session
        session.rollback()  # Rollback after each test
```

**Features:**
- In-memory SQLite (no persistence)
- Fast test execution
- Automatic rollback after each test
- No connection pooling (single connection)

## Configuration Validation

### Runtime Config Validation

The application uses Pydantic models to validate configuration:

```python
# src/app/runtime/config/config_data.py
from pydantic import BaseModel, Field

class DatabaseConfig(BaseModel):
    """Database configuration model."""
    
    url: str = Field(
        default="postgresql://user:password@localhost:5432/appdb",
        description="Database connection URL"
    )
    pool_size: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Connection pool size"
    )
    max_overflow: int = Field(
        default=10,
        ge=0,
        le=100,
        description="Max overflow connections"
    )
    pool_timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Connection timeout in seconds"
    )
    pool_recycle: int = Field(
        default=1800,
        ge=300,
        le=7200,
        description="Connection recycle time in seconds"
    )
```

**Validation Errors:**
```python
# Invalid pool_size (too large)
ValidationError: pool_size must be <= 100

# Invalid pool_timeout (too small)
ValidationError: pool_timeout must be >= 1
```

### Connection String Validation

The application validates connection strings at startup:

```python
from sqlalchemy import create_engine
from sqlalchemy.exc import ArgumentError

try:
    engine = create_engine(database_url)
except ArgumentError as e:
    logger.error(f"Invalid database URL: {e}")
    raise
```

**Common Errors:**

| Error | Cause | Solution |
|-------|-------|----------|
| `No such driver: postgres` | Missing `psycopg2` or `asyncpg` | Install driver: `uv add psycopg2-binary` |
| `Invalid connection string` | Malformed URL | Check format: `postgresql://user:pass@host:port/db` |
| `Could not translate host name` | Invalid hostname | Check DNS resolution |
| `Connection refused` | PostgreSQL not running | Start database: `uv run cli dev start-env` |

## Performance Tuning

### Application-Level Tuning

**Connection Pool Optimization:**
```yaml
# For read-heavy workloads
database:
  pool_size: 30              # More persistent connections
  max_overflow: 5            # Less overflow
  pool_recycle: 3600         # Longer recycle time

# For write-heavy workloads
database:
  pool_size: 15              # Fewer persistent connections
  max_overflow: 15           # More overflow capacity
  pool_timeout: 60           # Longer timeout
```

**Query Optimization:**
```python
# Enable SQLAlchemy query logging (development only)
engine = create_engine(
    database_url,
    echo=True,              # Log all SQL queries
    echo_pool=True,         # Log pool operations
)
```

### Database-Level Tuning

**Memory Settings (adjust based on available RAM):**
```properties
# For 8GB RAM system
shared_buffers = 2GB              # 25% of RAM
effective_cache_size = 6GB        # 75% of RAM
work_mem = 8MB                    # RAM / max_connections
maintenance_work_mem = 512MB      # RAM / 16

# For 16GB RAM system
shared_buffers = 4GB
effective_cache_size = 12GB
work_mem = 16MB
maintenance_work_mem = 1GB
```

**Query Planner:**
```properties
# SSD-optimized (default: 4.0)
random_page_cost = 1.1

# HDD-optimized
random_page_cost = 4.0

# Parallel query execution (CPU cores - 1)
max_parallel_workers_per_gather = 4
max_worker_processes = 8
```

**WAL and Checkpoints:**
```properties
# For write-heavy workloads
wal_buffers = 32MB                # Larger WAL buffer
max_wal_size = 2GB                # Larger WAL size
checkpoint_completion_target = 0.9

# For read-heavy workloads
wal_buffers = 16MB
max_wal_size = 1GB
checkpoint_completion_target = 0.5
```

## Troubleshooting

### Configuration Issues

**Issue: "Could not connect to database"**

**Check:**
1. Database is running: `uv run cli dev status`
2. Connection string is correct: `echo $DATABASE_URL`
3. Host is reachable: `pg_isready -h localhost -p 5433`
4. Firewall allows connections: `telnet localhost 5433`

**Solution:**
```bash
# Start development environment
uv run cli dev start-env

# Wait for database to be ready
uv run cli dev logs postgres

# Test connection
docker exec -it api-forge-postgres-dev psql -U postgres -c "SELECT 1"
```

**Issue: "Pool timeout exceeded"**

**Symptoms:**
```
TimeoutError: QueuePool limit of size 20 overflow 10 reached
```

**Solutions:**
1. Increase pool size: `pool_size: 30`
2. Check for connection leaks (missing `session.close()`)
3. Reduce `pool_timeout` to fail faster: `pool_timeout: 10`

**Issue: "SSL connection required"**

**Symptoms:**
```
OperationalError: server requires SSL connection
```

**Solutions:**
1. Add SSL mode to connection string: `?sslmode=require`
2. Disable SSL (development only): `ssl = off` in postgresql.conf
3. Provide SSL certificates: `sslrootcert=/path/to/ca.crt`

### Environment Variable Issues

**Issue: "Environment variable not set"**

**Check:**
```bash
# List all database-related variables
env | grep -i database
env | grep -i postgres

# Check .env file exists
ls -la .env

# Source .env file
export $(cat .env | xargs)
```

**Issue: "Password authentication failed"**

**Solutions:**
1. Check password in .env matches database
2. Verify SCRAM-SHA-256 is enabled in pg_hba.conf
3. Reset password:
```bash
docker exec -it api-forge-postgres-dev psql -U postgres
ALTER USER appuser PASSWORD 'newpassword';
```

## Security Considerations

### Password Management

**Development:**
- Hardcoded passwords acceptable
- Use simple passwords: `devpass`
- Never commit production passwords

**Production:**
- Use Docker secrets
- Generate with `infra/secrets/generate_secrets.sh`
- Store in encrypted vault (AWS Secrets Manager, HashiCorp Vault)
- Rotate regularly (every 90 days)

### TLS/SSL Configuration

**Required for Production:**
```properties
ssl = on
ssl_min_protocol_version = 'TLSv1.2'
ssl_cert_file = '/etc/postgresql/ssl/server.crt'
ssl_key_file = '/etc/postgresql/ssl/server.key'
```

**Certificate Generation:**
```bash
# Generate secrets including TLS certificates
cd infra/secrets
./generate_secrets.sh
```

**Client Configuration:**
```bash
# Require SSL
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require

# Verify CA certificate
DATABASE_URL=postgresql://user:pass@host/db?sslmode=verify-ca&sslrootcert=/run/secrets/ca-bundle.crt

# Full verification (hostname + CA)
DATABASE_URL=postgresql://user:pass@host/db?sslmode=verify-full&sslrootcert=/run/secrets/ca-bundle.crt
```

## Related Documentation

- [Main Documentation](./main.md) - PostgreSQL overview and architecture
- [Usage Guide](./usage.md) - Code examples and patterns
- [Security Guide](./security.md) - Detailed security configuration
- [Migrations Guide](./migrations.md) - Schema management
- [Secrets Management](../secrets_management.md) - Password and certificate management
- [Production Deployment](../PRODUCTION_DEPLOYMENT.md) - Production PostgreSQL setup
