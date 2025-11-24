# FastAPI Production Deployment with Docker Compose

Learn how to deploy your FastAPI application to production using Docker Compose with TLS/mTLS encryption, secret management, and security hardening. This guide covers the production Docker Compose configuration included with API Forge for deploying secure, production-ready FastAPI microservices.

## Overview

API Forge includes a production-ready Docker Compose configuration (`docker-compose.prod.yml`) that provides:

- **TLS/mTLS Encryption** - Full certificate-based encryption between all services
- **Secret Management** - File-based secrets with secure permissions
- **PostgreSQL with SCRAM-SHA-256** - Production database with strong authentication
- **Redis with TLS** - Encrypted cache and session storage
- **Temporal with mTLS** - Secure workflow orchestration
- **Nginx Reverse Proxy** - TLS termination and routing
- **Health Checks** - Automated service monitoring
- **Resource Limits** - CPU and memory constraints
- **Separate Network** - Isolated production network

This setup is suitable for small to medium production deployments on a single host or VM.

## Quick Start

Deploy to production with Docker Compose:

```bash
# Generate secrets and certificates
cd infra/secrets
./generate_secrets.sh

# Copy deterministic secret template and fill OIDC client secrets, webhook tokens, etc.
cp user-provided.env.example user-provided.env
# Edit user-provided.env with production-only values (not committed to git)

# Create .env file with production values
cp .env.example .env
# Edit .env with production configuration

# Deploy all services
uv run api-forge-cli deploy up prod

# Check status
uv run api-forge-cli deploy status prod
```

Your FastAPI application will be available at https://your-domain.com with full TLS encryption.

## Architecture

### Service Components

```
┌─────────────────────────────────────────────────────────┐
│                      Internet                            │
└────────────────────┬────────────────────────────────────┘
                     │ HTTPS (443)
              ┌──────▼──────┐
              │    Nginx    │ TLS Termination
              │  (Reverse   │ Rate Limiting
              │   Proxy)    │ Load Balancing
              └──────┬──────┘
                     │ HTTP (internal)
         ┌───────────┴───────────┐
         │                       │
    ┌────▼─────┐          ┌─────▼────┐
    │   App    │          │  Worker  │
    │ FastAPI  │          │ (Temporal)│
    │  Server  │          │          │
    └────┬─────┘          └─────┬────┘
         │                      │
    ┌────┴──────────────────────┴────┐
    │                                 │
┌───▼────────┐  ┌──────────┐  ┌──────▼──────┐
│ PostgreSQL │  │  Redis   │  │  Temporal   │
│   (TLS)    │  │  (TLS)   │  │   (mTLS)    │
└────────────┘  └──────────┘  └─────────────┘
```

### Network Security

All services communicate over an isolated Docker network with encryption:

- **External → Nginx**: TLS 1.3
- **Nginx → App**: HTTP (internal network)
- **App → PostgreSQL**: TLS with certificate verification
- **App → Redis**: TLS with authentication
- **App → Temporal**: mTLS (mutual TLS)
- **Worker → Temporal**: mTLS

## Secret Management

### Generating Secrets

API Forge includes a script to generate all required secrets and certificates:

```bash
cd infra/secrets
./generate_secrets.sh
```

This generates:

**Application Secrets**:
- `session_signing_secret` - Session cookie signing (64 bytes)
- `csrf_signing_secret` - CSRF token signing (64 bytes)
- `jwt_signing_secret` - JWT token signing (64 bytes)

**Database Secrets**:
- `postgres_password` - PostgreSQL superuser password
- `postgres_app_owner_pw` - Database owner password
- `postgres_app_user_pw` - Application user password
- `postgres_app_ro_pw` - Read-only user password
- `postgres_temporal_pw` - Temporal user password

**TLS Certificates**:
- `postgres_server_ca.crt` - PostgreSQL CA certificate
- `postgres_tls.crt` - PostgreSQL server certificate
- `postgres_tls.key` - PostgreSQL private key
- `redis_ca.crt` - Redis CA certificate
- `redis.crt` - Redis server certificate
- `redis.key` - Redis private key
- `temporal_client.crt` - Temporal client certificate
- `temporal_client.key` - Temporal client key

> ℹ️ Deterministic credentials (OIDC client secrets, webhook tokens, vendor API keys, etc.) are **not** generated automatically. Store those values in `infra/secrets/user-provided.env` (copied from the `.example` file) and keep it out of version control. The production Compose stack now mounts this file via `env_file` so `app` and `worker` receive `OIDC_*_CLIENT_SECRET` at runtime.

### Using Docker Secrets

The production configuration uses Docker secrets for sensitive data:

```yaml
# docker-compose.prod.yml
secrets:
  session_signing_secret:
    file: /run/secrets/session_signing_secret
  
  postgres_password:
    file: /run/secrets/postgres_password
  
  postgres_tls_cert:
    file: /run/secrets/postgres_tls.crt

services:
  app:
    secrets:
      - session_signing_secret
      - postgres_app_user_pw
      - redis_password
```

Secrets are mounted as files in `/run/secrets/` within containers.

For deterministic values that live outside the generator (like OIDC client secrets), `docker-compose.prod.yml` now includes `infra/secrets/user-provided.env` in the `env_file` list for the `app` and `worker` services. Populate that file locally and Docker Compose will inject the variables alongside those from `.env`.

### Reading Secrets in Application

Your FastAPI application reads secrets from files:

```python
# In config.yaml
app:
  session:
    signing_secret_file: /run/secrets/session_signing_secret
    
database:
  password_file: /run/secrets/postgres_app_user_pw

redis:
  password_file: /run/secrets/redis_password
```

Configuration loader automatically reads from file if `*_file` variant is used.

## PostgreSQL Production Configuration

### TLS Setup

PostgreSQL runs with TLS enabled and enforced:

```yaml
# docker-compose.prod.yml
postgres:
  image: postgres:16
  environment:
    POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
  volumes:
    - ./docker/prod/postgres/postgresql.conf:/etc/postgresql/postgresql.conf
    - ./docker/prod/postgres/pg_hba.conf:/etc/postgresql/pg_hba.conf
  secrets:
    - postgres_password
    - postgres_tls_cert
    - postgres_tls_key
    - postgres_server_ca
  command: postgres -c config_file=/etc/postgresql/postgresql.conf
```

**postgresql.conf** (key settings):
```conf
# TLS/SSL Configuration
ssl = on
ssl_cert_file = '/run/secrets/postgres_tls.crt'
ssl_key_file = '/run/secrets/postgres_tls.key'
ssl_ca_file = '/run/secrets/postgres_server_ca.crt'
ssl_ciphers = 'HIGH:!aNULL:!MD5'
ssl_prefer_server_ciphers = on
ssl_min_protocol_version = 'TLSv1.3'

# Authentication
password_encryption = scram-sha-256

# Performance
shared_buffers = 256MB
effective_cache_size = 1GB
maintenance_work_mem = 128MB
max_connections = 100

# Write-Ahead Log
wal_level = replica
max_wal_size = 2GB
```

**pg_hba.conf** (authentication):
```conf
# Require SCRAM-SHA-256 authentication over TLS
hostssl all all all scram-sha-256
```

### Database Users

The production setup creates multiple users with least-privilege:

```sql
-- Database owner (DDL operations)
CREATE USER appowner WITH PASSWORD 'from_secret';
GRANT ALL PRIVILEGES ON DATABASE appdb TO appowner;

-- Application user (read/write)
CREATE USER appuser WITH PASSWORD 'from_secret';
GRANT CONNECT ON DATABASE appdb TO appuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO appuser;

-- Read-only user (reporting/analytics)
CREATE USER approuser WITH PASSWORD 'from_secret';
GRANT CONNECT ON DATABASE appdb TO approuser;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO approuser;

-- Temporal user (workflow engine)
CREATE USER temporaluser WITH PASSWORD 'from_secret';
GRANT ALL PRIVILEGES ON SCHEMA temporal TO temporaluser;
GRANT ALL PRIVILEGES ON SCHEMA temporal_visibility TO temporaluser;
```

### Connection String

Application connects using TLS:

```python
# In .env or config
DATABASE_URL=postgresql://appuser@postgres:5432/appdb?sslmode=verify-full&sslrootcert=/run/secrets/postgres_server_ca.crt
```

Parameters:
- `sslmode=verify-full` - Verify server certificate and hostname
- `sslrootcert` - Path to CA certificate for verification

## Redis Production Configuration

### TLS Setup

Redis runs with TLS encryption:

```yaml
# docker-compose.prod.yml
redis:
  image: redis:7
  volumes:
    - ./docker/prod/redis/redis.conf:/usr/local/etc/redis/redis.conf
  secrets:
    - redis_password
    - redis_tls_cert
    - redis_tls_key
    - redis_ca
  command: redis-server /usr/local/etc/redis/redis.conf
```

**redis.conf** (key settings):
```conf
# TLS Configuration
tls-port 6379
port 0
tls-cert-file /run/secrets/redis.crt
tls-key-file /run/secrets/redis.key
tls-ca-cert-file /run/secrets/redis_ca.crt
tls-auth-clients no
tls-protocols "TLSv1.3"

# Authentication
requirepass <from_file>

# Performance
maxmemory 512mb
maxmemory-policy allkeys-lru

# Persistence
save 900 1
save 300 10
save 60 10000
appendonly yes
```

### Connection String

Application connects using TLS:

```python
# In .env or config
REDIS_URL=rediss://:password@redis:6379/0?ssl_cert_reqs=required&ssl_ca_certs=/run/secrets/redis_ca.crt
```

Note: `rediss://` (with double 's') indicates TLS connection.

## Temporal Production Configuration

### mTLS Setup

Temporal uses mutual TLS for authentication:

```yaml
# docker-compose.prod.yml
temporal:
  image: temporalio/auto-setup:1.29.0
  environment:
    - DB=postgresql
    - POSTGRES_SEEDS=postgres
    - TEMPORAL_TLS_REQUIRE_CLIENT_AUTH=true
    - TEMPORAL_TLS_SERVER_CA_CERT=/run/secrets/temporal_ca.crt
    - TEMPORAL_TLS_SERVER_CERT=/run/secrets/temporal_server.crt
    - TEMPORAL_TLS_SERVER_KEY=/run/secrets/temporal_server.key
  secrets:
    - temporal_server_cert
    - temporal_server_key
    - temporal_ca
```

### Worker Configuration

Workers authenticate using client certificates:

```python
# In worker configuration
from temporalio.client import Client, TLSConfig

tls_config = TLSConfig(
    server_root_ca_cert=open("/run/secrets/temporal_ca.crt", "rb").read(),
    client_cert=open("/run/secrets/temporal_client.crt", "rb").read(),
    client_private_key=open("/run/secrets/temporal_client.key", "rb").read(),
)

client = await Client.connect(
    "temporal:7233",
    namespace="production",
    tls=tls_config,
)
```

## Nginx Configuration

### TLS Termination

Nginx handles TLS termination for external traffic:

```nginx
# docker/prod/nginx/nginx.conf
server {
    listen 443 ssl http2;
    server_name api.example.com;

    # TLS Configuration
    ssl_certificate /etc/nginx/ssl/server.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;
    ssl_protocols TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Rate Limiting
    limit_req zone=api_limit burst=20 nodelay;

    # Proxy to FastAPI
    location / {
        proxy_pass http://app:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Health check endpoint
    location /health {
        proxy_pass http://app:8000/health;
        access_log off;
    }
}

# HTTP redirect to HTTPS
server {
    listen 80;
    server_name api.example.com;
    return 301 https://$server_name$request_uri;
}
```

### Rate Limiting

Configure rate limits to prevent abuse:

```nginx
# In http block
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=login_limit:10m rate=5r/m;

server {
    # General API rate limit
    location /api/ {
        limit_req zone=api_limit burst=20 nodelay;
        proxy_pass http://app:8000;
    }

    # Stricter limit for auth endpoints
    location /auth/ {
        limit_req zone=login_limit burst=5 nodelay;
        proxy_pass http://app:8000;
    }
}
```

## Application Configuration

### Production Environment Variables

```bash
# .env for production
APP_ENVIRONMENT=production
APP_NAME=My Production API
APP_VERSION=1.0.0

# Database (using secrets)
DATABASE_URL=postgresql://appuser@postgres:5432/appdb?sslmode=verify-full
DATABASE_PASSWORD_FILE=/run/secrets/postgres_app_user_pw

# Redis (using secrets)
REDIS_URL=rediss://:password@redis:6379/0
REDIS_PASSWORD_FILE=/run/secrets/redis_password

# Temporal
TEMPORAL_URL=temporal:7233
TEMPORAL_NAMESPACE=production
TEMPORAL_TLS_ENABLED=true

# Sessions (using secrets)
SESSION_SIGNING_SECRET_FILE=/run/secrets/session_signing_secret
CSRF_SIGNING_SECRET_FILE=/run/secrets/csrf_signing_secret

# OIDC Providers (production)
# Place these in infra/secrets/user-provided.env so docker-compose.prod.yml can load them
OIDC_GOOGLE_CLIENT_ID=your-google-client-id
OIDC_GOOGLE_CLIENT_SECRET=your-google-client-secret

OIDC_MICROSOFT_CLIENT_ID=your-microsoft-client-id
OIDC_MICROSOFT_CLIENT_SECRET=your-microsoft-client-secret

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# CORS
ALLOWED_ORIGINS=https://app.example.com,https://www.example.com
```

### Configuration File

```yaml
# config.yaml for production
app:
  environment: production
  session:
    signing_secret_file: /run/secrets/session_signing_secret
    secure: true  # HttpOnly, Secure flags
    same_site: strict
    max_age: 3600  # 1 hour
    rotation_interval: 1800  # Rotate every 30 minutes

database:
  connection_string: ${DATABASE_URL}
  password_file: /run/secrets/postgres_app_user_pw
  pool_size: 20
  max_overflow: 10
  pool_timeout: 30
  ssl_mode: verify-full
  ssl_ca_cert: /run/secrets/postgres_server_ca.crt

redis:
  url: ${REDIS_URL}
  password_file: /run/secrets/redis_password
  tls: true
  ssl_ca_cert: /run/secrets/redis_ca.crt

temporal:
  url: temporal:7233
  namespace: production
  tls_enabled: true
  client_cert: /run/secrets/temporal_client.crt
  client_key: /run/secrets/temporal_client.key
  server_ca_cert: /run/secrets/temporal_ca.crt

logging:
  level: INFO
  format: json
  handlers:
    - type: file
      filename: /app/logs/app.log
      rotation: daily
      retention: 30
    - type: console
```

## Resource Limits

### Docker Compose Resource Configuration

```yaml
# docker-compose.prod.yml
services:
  app:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '1.0'
          memory: 1G
    restart: unless-stopped

  postgres:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '1.0'
          memory: 1G
    restart: unless-stopped

  redis:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.5'
          memory: 256M
    restart: unless-stopped

  temporal:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '1.0'
          memory: 1G
    restart: unless-stopped
```

### Tuning Recommendations

Based on workload:

**Low Traffic** (< 100 req/s):
- App: 1 CPU, 1GB RAM
- PostgreSQL: 1 CPU, 1GB RAM
- Redis: 0.5 CPU, 256MB RAM

**Medium Traffic** (100-500 req/s):
- App: 2 CPU, 2GB RAM (scale horizontally)
- PostgreSQL: 2 CPU, 4GB RAM
- Redis: 1 CPU, 512MB RAM

**High Traffic** (> 500 req/s):
- Consider Kubernetes deployment (see [FastAPI Kubernetes Deployment](./fastapi-kubernetes-deployment.md))

## Health Checks

### Docker Compose Health Checks

```yaml
# docker-compose.prod.yml
services:
  app:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health/live"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  postgres:
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U appuser"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    healthcheck:
      test: ["CMD", "redis-cli", "--tls", "--cacert", "/run/secrets/redis_ca.crt", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
```

### Application Health Endpoints

FastAPI application provides health endpoints:

```python
# Liveness probe - is the app running?
@app.get("/health/live")
async def liveness():
    return {"status": "ok"}

# Readiness probe - can it handle requests?
@app.get("/health/ready")
async def readiness(db: Session = Depends(get_db)):
    try:
        # Check database
        db.execute("SELECT 1")
        
        # Check Redis
        redis_client.ping()
        
        return {"status": "ready", "checks": {"db": "ok", "redis": "ok"}}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Not ready: {e}")
```

## Deployment Workflow

### Initial Deployment

```bash
# 1. Prepare secrets
cd infra/secrets
./generate_secrets.sh

# 2. Configure environment
cp .env.example .env
# Edit .env with production values

# 3. Build Docker images
docker build -t my-api:latest -f docker/prod/Dockerfile .

# 4. Deploy services
uv run api-forge-cli deploy up prod

# 5. Verify deployment
uv run api-forge-cli deploy status prod
curl -f https://your-domain.com/health/ready
```

### Updating the Application

```bash
# 1. Build new image
docker build -t my-api:v1.1.0 -f docker/prod/Dockerfile .

# 2. Update docker-compose.prod.yml with new image tag
# services:
#   app:
#     image: my-api:v1.1.0

# 3. Deploy with rolling restart
docker-compose -f docker-compose.prod.yml up -d app

# 4. Verify health
curl -f https://your-domain.com/health/ready
```

### Zero-Downtime Updates

For zero-downtime deployments, scale up before down:

```bash
# 1. Scale to 2 instances
docker-compose -f docker-compose.prod.yml up -d --scale app=2

# 2. Wait for new instance to be healthy
sleep 30

# 3. Remove old instance
docker stop <old_container_id>

# 4. Scale back to 1
docker-compose -f docker-compose.prod.yml up -d --scale app=1
```

## Backups

### PostgreSQL Backups

```bash
# Manual backup
docker exec api-forge-postgres-prod pg_dump -U appuser appdb > backup-$(date +%Y%m%d-%H%M%S).sql

# Automated backups (add to crontab)
0 2 * * * docker exec api-forge-postgres-prod pg_dump -U appuser appdb | gzip > /backups/appdb-$(date +\%Y\%m\%d).sql.gz

# Restore from backup
gunzip < backup-20240101.sql.gz | docker exec -i api-forge-postgres-prod psql -U appuser appdb
```

### Redis Backups

```bash
# Trigger Redis save
docker exec api-forge-redis-prod redis-cli --tls --cacert /run/secrets/redis_ca.crt BGSAVE

# Copy RDB file
docker cp api-forge-redis-prod:/data/dump.rdb redis-backup-$(date +%Y%m%d).rdb

# Restore (stop Redis first)
docker cp redis-backup-20240101.rdb api-forge-redis-prod:/data/dump.rdb
docker restart api-forge-redis-prod
```

### Volume Backups

```bash
# Backup PostgreSQL volume
docker run --rm -v api-forge-postgres-data:/data -v $(pwd):/backup alpine tar czf /backup/postgres-data-backup.tar.gz -C /data .

# Restore PostgreSQL volume
docker run --rm -v api-forge-postgres-data:/data -v $(pwd):/backup alpine tar xzf /backup/postgres-data-backup.tar.gz -C /data
```

## Monitoring

### Log Aggregation

Collect logs from all containers:

```bash
# View all logs
docker-compose -f docker-compose.prod.yml logs -f

# Filter by service
docker-compose -f docker-compose.prod.yml logs -f app

# Export logs to file
docker-compose -f docker-compose.prod.yml logs --since 24h > logs-$(date +%Y%m%d).txt
```

### Metrics Collection

Consider adding Prometheus and Grafana:

```yaml
# docker-compose.prod.yml
services:
  prometheus:
    image: prom/prometheus
    volumes:
      - ./docker/prod/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    networks:
      - prod-network

  grafana:
    image: grafana/grafana
    volumes:
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    networks:
      - prod-network
```

### Application Metrics

FastAPI application can expose Prometheus metrics:

```python
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

# Instrument FastAPI app
Instrumentator().instrument(app).expose(app)

# Custom metrics
request_count = Counter('api_requests_total', 'Total requests')
request_duration = Histogram('api_request_duration_seconds', 'Request duration')
```

## Security Hardening

### Docker Security

```yaml
# docker-compose.prod.yml
services:
  app:
    # Run as non-root user
    user: "1000:1000"
    
    # Drop capabilities
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
    
    # Read-only root filesystem
    read_only: true
    tmpfs:
      - /tmp
      - /app/logs
    
    # No new privileges
    security_opt:
      - no-new-privileges:true
```

### Network Isolation

```yaml
# docker-compose.prod.yml
networks:
  prod-network:
    driver: bridge
    internal: true  # No external access
  
  public-network:
    driver: bridge
    
services:
  nginx:
    networks:
      - public-network
      - prod-network
  
  app:
    networks:
      - prod-network  # Only internal network
```

### File Permissions

```bash
# Restrict secret file permissions
sudo chmod 400 /run/secrets/*
sudo chown root:root /run/secrets/*

# Application files
sudo chown -R 1000:1000 /app
sudo chmod -R 755 /app
sudo chmod -R 644 /app/config.yaml
```

## Troubleshooting

### Services Won't Start

**Check Docker resources**:
```bash
docker system df
docker system prune  # Clean up if needed
```

**View service logs**:
```bash
docker-compose -f docker-compose.prod.yml logs postgres
docker-compose -f docker-compose.prod.yml logs redis
docker-compose -f docker-compose.prod.yml logs app
```

**Verify secrets exist**:
```bash
docker exec -it api-forge-postgres-prod ls -la /run/secrets/
# Should show all required secret files
```

### TLS Connection Errors

**PostgreSQL TLS issues**:
```bash
# Test PostgreSQL connection with TLS
docker exec -it api-forge-postgres-prod psql -U appuser -d appdb -c "SELECT version();"

# Check TLS status
docker exec -it api-forge-postgres-prod psql -U appuser -d appdb -c "SHOW ssl;"
```

**Redis TLS issues**:
```bash
# Test Redis connection with TLS
docker exec api-forge-redis-prod redis-cli --tls --cacert /run/secrets/redis_ca.crt PING
```

### Performance Issues

**Check resource usage**:
```bash
docker stats
```

**PostgreSQL performance**:
```sql
-- Check active connections
SELECT count(*) FROM pg_stat_activity;

-- Check slow queries
SELECT query, calls, mean_exec_time 
FROM pg_stat_statements 
ORDER BY mean_exec_time DESC 
LIMIT 10;
```

**Redis performance**:
```bash
# Check memory usage
docker exec api-forge-redis-prod redis-cli --tls --cacert /run/secrets/redis_ca.crt INFO memory

# Check slow log
docker exec api-forge-redis-prod redis-cli --tls --cacert /run/secrets/redis_ca.crt SLOWLOG GET 10
```

## Migration from Development

Key differences when moving from dev to production:

| Configuration | Development | Production |
|---------------|-------------|------------|
| Secrets | Hardcoded in .env | Docker secrets from files |
| TLS | Disabled | Required for all services |
| Ports | Offset (+1000) | Standard ports |
| Authentication | Simple passwords | SCRAM-SHA-256 |
| Session cookies | Secure=false | Secure=true |
| Logging | DEBUG to console | INFO to files (JSON) |
| CORS | Permissive | Strict origin list |
| Resource limits | None | CPU/memory limits |

## Related Documentation

- [FastAPI Kubernetes Deployment](./fastapi-kubernetes-deployment.md) - For larger production deployments
- [FastAPI Docker Development Environment](./fastapi-docker-dev-environment.md) - Local development setup
- [FastAPI Sessions and Cookies](./fastapi-sessions-and-cookies.md) - Session security in production

## Additional Resources

- [Docker Compose Production Best Practices](https://docs.docker.com/compose/production/)
- [PostgreSQL Security Checklist](https://www.postgresql.org/docs/current/ssl-tcp.html)
- [Redis Security Guide](https://redis.io/topics/security)
- [OWASP Docker Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html)
