# Production Deployment Guide

This guide covers the deployment of the FastAPI application stack to production environments using the API Forge CLI. For detailed deployment guides, see:

- **[Docker Compose Production](../fastapi-production-deployment-docker-compose.md)** - Single-host deployments
- **[Kubernetes Deployment](../fastapi-kubernetes-deployment.md)** - Scalable cluster deployments

## 🏗️ Architecture Overview

### Production Stack
- **Application**: FastAPI with OIDC authentication, session management, and rate limiting
- **Database**: PostgreSQL 16 with SSL, backup automation, and performance tuning
- **Cache/Sessions**: Redis 7 with persistence, security hardening, and memory optimization
- **Workflows**: Temporal Server with PostgreSQL backend for reliable workflow execution
- **Reverse Proxy**: Nginx with SSL termination, security headers, and load balancing

### Security Features
- **Container Security**: Non-root users, minimal attack surface, signed images
- **Network Security**: Internal networking, firewall rules, SSL/TLS encryption
- **Data Security**: Encrypted connections, secure password storage, backup encryption
- **Application Security**: CSRF protection, rate limiting, security headers, OIDC compliance

## 🚀 Quick Start

### Prerequisites
- Docker and Docker Compose installed
- `uv` package manager installed
- Domain name configured (for SSL certificates)
- At least 2GB RAM and 20GB storage
- OIDC provider credentials (Google, Microsoft, etc.)

### 1. Clone and Setup
```bash
git clone <your-repo>
cd your-project

# Install dependencies
uv sync --dev

# Copy and configure environment
cp .env.example .env
# Edit .env with production configuration values
```

### 2. Generate Secrets
```bash
# Generate all secrets and TLS certificates
cd infra/secrets
./generate_secrets.sh

# Copy user-provided secrets template and fill in OIDC credentials
cp user-provided.env.example user-provided.env
# Edit user-provided.env with your OIDC client secrets
```

### 3. Deploy

**Docker Compose (single host):**
```bash
uv run api-forge-cli deploy up prod

# Check deployment status
uv run api-forge-cli deploy status prod
```

**Kubernetes (cluster deployment):**
```bash
uv run api-forge-cli deploy up k8s

# Check deployment status
uv run api-forge-cli deploy status k8s

# View release history
uv run api-forge-cli deploy history
```

### 4. Verify Deployment
```bash
# Check service health
curl https://yourdomain.com/health
curl https://yourdomain.com/health/ready

# View service logs (Docker Compose)
docker-compose -f docker-compose.prod.yml logs -f

# View pod logs (Kubernetes)
kubectl logs -n api-forge-prod -l app.kubernetes.io/name=app -f
```

## 🔧 Configuration

### Environment Variables

#### Application Configuration
```env
APP_ENVIRONMENT=production
BASE_URL=https://yourdomain.com
APP_PORT=8000

# Database
DATABASE_URL=postgresql://appuser@postgres:5432/appdb?sslmode=verify-full

# Redis
REDIS_URL=rediss://:password@redis:6379/0

# JWT & Sessions (use file-based secrets)
JWT_AUDIENCE=api://default
SESSION_MAX_AGE=3600
SESSION_SIGNING_SECRET_FILE=/run/secrets/session_signing_secret
CSRF_SIGNING_SECRET_FILE=/run/secrets/csrf_signing_secret

# CORS
CLIENT_ORIGIN=https://yourdomain.com
```

#### OIDC Configuration
Store OIDC secrets in `infra/secrets/user-provided.env`:
```env
# Google OAuth
OIDC_GOOGLE_CLIENT_ID=your-google-client-id
OIDC_GOOGLE_CLIENT_SECRET=your-google-client-secret

# Microsoft OAuth
OIDC_MICROSOFT_CLIENT_ID=your-microsoft-client-id
OIDC_MICROSOFT_CLIENT_SECRET=your-microsoft-client-secret
```

### Secret Management
All sensitive data is stored in `infra/secrets/` with restricted permissions:

```bash
# Auto-generated secrets (in infra/secrets/keys/)
session_signing_secret.txt
csrf_signing_secret.txt
postgres_password.txt
postgres_app_user_pw.txt
redis_password.txt

# User-provided secrets (in infra/secrets/user-provided.env)
OIDC_GOOGLE_CLIENT_SECRET=...
OIDC_MICROSOFT_CLIENT_SECRET=...
```

For Docker Compose-based deployments, keep deterministic secrets such as `OIDC_*_CLIENT_SECRET`
inside `infra/secrets/user-provided.env` (copied from the `.example`), which is mounted via
`env_file`. When deploying to Kubernetes, these values are created as Kubernetes secrets.

## 🛡️ Security Considerations

### Container Security
- **Non-root execution**: All services run as non-privileged users
- **Minimal images**: Alpine Linux base images with only necessary packages
- **Security scanning**: Regular vulnerability scans recommended
- **Resource limits**: Memory and CPU limits configured in docker-compose
- **Consistent naming**: Hardcoded container names ensure portability across deployments:
  - `app_data_postgres_db` - PostgreSQL database
  - `app_data_redis_cache` - Redis cache/session store
  - `app_data_temporal_server` - Temporal workflow engine
  - `app_data_fastapi_app` - FastAPI application
  - `app_data_nginx_proxy` - Nginx reverse proxy

### Network Security
- **Internal networking**: Services communicate on internal Docker networks
- **Firewall rules**: UFW configured to allow only HTTP/HTTPS/SSH
- **SSL/TLS**: Let's Encrypt certificates with automatic renewal
- **Security headers**: HSTS, CSRF protection, content type validation

### Database Security
- **Encrypted connections**: SSL required for all database connections
- **Authentication**: SCRAM-SHA-256 password encryption
- **Access control**: Restricted user permissions and schema isolation
- **Audit logging**: Connection and query logging enabled

### Application Security
- **OIDC compliance**: Proper OAuth2/OIDC implementation with PKCE
- **Session security**: Secure session management with Redis backend
- **Rate limiting**: Redis-based rate limiting for API endpoints
- **CSRF protection**: Built-in CSRF token validation

## 📊 Monitoring & Observability

### Health Checks
- **Application**: `/health` and `/ready` endpoints
- **Database**: `pg_isready` health checks
- **Redis**: `redis-cli ping` health checks
- **Temporal**: Built-in health check endpoints

### Logging
- **Application logs**: Structured logging with request tracing
- **Database logs**: Query logging and connection auditing
- **System logs**: Docker and system-level logging
- **Log rotation**: Automatic log rotation with 30-day retention

### Metrics Collection
```bash
# View container stats
docker stats

# Check service health
docker-compose -f docker-compose.prod.yml ps

# Monitor disk usage
df -h /opt/app

# Check backup status
ls -la /opt/app/backups/
```

## 💾 Backup & Recovery

### Automated Backups
Daily backups are configured via cron jobs:

```bash
# Database backup (2:00 AM daily)
0 2 * * * root docker exec $(docker ps -q -f name=postgres) /usr/local/bin/backup.sh

# Redis backup (2:30 AM daily)
30 2 * * * root docker exec $(docker ps -q -f name=redis) /usr/local/bin/backup.sh
```

### Manual Backup
```bash
# Database backup
docker exec $(docker ps -q -f name=postgres) /usr/local/bin/backup.sh

# Redis backup
docker exec $(docker ps -q -f name=redis) /usr/local/bin/backup.sh

# Copy backups to external storage
rsync -av /opt/app/backups/ user@backup-server:/backups/
```

### Recovery Procedures
```bash
# Restore PostgreSQL
docker exec -i $(docker ps -q -f name=postgres) pg_restore \
    --host=localhost --username=appuser --dbname=appdb \
    --clean --if-exists < backup_file.dump

# Restore Redis
docker exec -i $(docker ps -q -f name=redis) redis-cli \
    --rdb backup_file.rdb
```

## 🔄 Maintenance

### Updates

**Docker Compose:**
```bash
# Build and deploy updated application
uv run api-forge-cli deploy up prod --force-recreate

# Or manually update
docker-compose -f docker-compose.prod.yml pull app
docker-compose -f docker-compose.prod.yml up -d app
```

**Kubernetes:**
```bash
# Deploy updated application
uv run api-forge-cli deploy up k8s

# View release history
uv run api-forge-cli deploy history

# Rollback if needed
uv run api-forge-cli deploy rollback
```

### SSL Certificate Renewal
```bash
# Manual renewal (if using Let's Encrypt)
certbot renew

# Automatic renewal is typically configured via cron or systemd timer
```

### Database Maintenance

**Docker Compose:**
```bash
# Connect to database
docker exec -it api-forge-postgres-prod psql -U appuser -d appdb

# Run VACUUM and ANALYZE
docker exec api-forge-postgres-prod psql -U appuser -d appdb -c "VACUUM ANALYZE;"
```

**Kubernetes:**
```bash
# Connect to database pod
kubectl exec -it -n api-forge-prod deployment/postgres -- psql -U appuser -d appdb

# Run maintenance
kubectl exec -n api-forge-prod deployment/postgres -- psql -U appuser -d appdb -c "VACUUM ANALYZE;"
```

## 🌐 Deployment Platforms

### Docker Compose (Single Host)
Suitable for small to medium deployments on a single VPS or VM:
```bash
uv run api-forge-cli deploy up prod
uv run api-forge-cli deploy status prod
```

See [Docker Compose Production Guide](../fastapi-production-deployment-docker-compose.md) for details.

### Kubernetes
For scalable, production-grade deployments:
```bash
uv run api-forge-cli deploy up k8s
uv run api-forge-cli deploy status k8s
uv run api-forge-cli deploy history
uv run api-forge-cli deploy rollback  # If needed
```

See [Kubernetes Deployment Guide](../fastapi-kubernetes-deployment.md) for details.

### Docker Swarm
```bash
# Initialize swarm
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.prod.yml app-stack
```

## 🚨 Troubleshooting

### Common Issues

#### Application Won't Start

**Docker Compose:**
```bash
# Check logs
docker-compose -f docker-compose.prod.yml logs app

# Verify environment configuration
docker-compose -f docker-compose.prod.yml config

# Check secret files
ls -la infra/secrets/keys/
```

**Kubernetes:**
```bash
# Check pod status
kubectl get pods -n api-forge-prod
kubectl describe pod -n api-forge-prod -l app.kubernetes.io/name=app

# View logs
kubectl logs -n api-forge-prod -l app.kubernetes.io/name=app

# Check secrets
kubectl get secrets -n api-forge-prod
```

#### Database Connection Issues

**Docker Compose:**
```bash
# Check PostgreSQL logs
docker-compose -f docker-compose.prod.yml logs postgres

# Test connection
docker exec -it api-forge-postgres-prod pg_isready -U appuser -d appdb

# Verify network connectivity
docker exec api-forge-app-prod nc -zv postgres 5432
```

**Kubernetes:**
```bash
# Check PostgreSQL pod
kubectl get pods -n api-forge-prod -l app.kubernetes.io/name=postgres
kubectl logs -n api-forge-prod -l app.kubernetes.io/name=postgres

# Test connection from app pod
kubectl exec -n api-forge-prod deployment/app -- nc -zv postgres 5432
```

#### Redis Connection Issues

**Docker Compose:**
```bash
# Check Redis logs
docker-compose -f docker-compose.prod.yml logs redis

# Test Redis connectivity
docker exec api-forge-redis-prod redis-cli ping
```

**Kubernetes:**
```bash
# Check Redis pod
kubectl get pods -n api-forge-prod -l app.kubernetes.io/name=redis
kubectl logs -n api-forge-prod -l app.kubernetes.io/name=redis
```

#### SSL Certificate Issues
```bash
# Check certificate status (if using Let's Encrypt)
certbot certificates

# Test SSL configuration
openssl s_client -connect yourdomain.com:443 -servername yourdomain.com

# Renew certificates
certbot renew --dry-run
```

#### Kubernetes Rollback
If a deployment causes issues:
```bash
# View release history
uv run api-forge-cli deploy history

# Rollback to previous version
uv run api-forge-cli deploy rollback

# Rollback to specific revision
uv run api-forge-cli deploy rollback 2
```

### Performance Tuning

#### PostgreSQL Optimization
- Adjust `shared_buffers` based on available RAM (25% of total RAM)
- Tune `work_mem` for query performance (start with 4MB)
- Monitor slow queries and add appropriate indexes

#### Redis Optimization
- Set `maxmemory` based on available RAM and usage patterns
- Use appropriate eviction policies (`allkeys-lru` for cache)
- Monitor memory usage and key distribution

#### Application Scaling
- Increase `APP_REPLICAS` in docker-compose for horizontal scaling
- Configure load balancer upstream servers
- Monitor application metrics and resource usage

## 📋 Checklist

### Pre-deployment
- [ ] Domain name configured and DNS pointing to server
- [ ] OIDC provider applications created and configured
- [ ] Secrets generated (`./infra/secrets/generate_secrets.sh`)
- [ ] User-provided secrets configured (`infra/secrets/user-provided.env`)
- [ ] `.env` file configured with production values
- [ ] Server resources adequate (2GB+ RAM, 20GB+ storage)
- [ ] Backup storage configured

### Post-deployment
- [ ] Health endpoints responding correctly (`/health`, `/health/ready`)
- [ ] OIDC authentication flows working
- [ ] SSL certificates installed (if applicable)
- [ ] Backup scripts tested and running
- [ ] Monitoring and alerting configured
- [ ] Firewall rules verified (if applicable)

### Kubernetes-specific
- [ ] `uv run api-forge-cli deploy status k8s` shows healthy pods
- [ ] `uv run api-forge-cli deploy history` shows successful deployment
- [ ] Rollback tested (`uv run api-forge-cli deploy rollback`)

### Security Audit
- [ ] All services running as non-root users
- [ ] Secrets properly secured with restricted permissions
- [ ] Database connections encrypted (TLS)
- [ ] API rate limiting functional
- [ ] Security headers properly configured
- [ ] Log files protected and rotated
- [ ] Regular security updates scheduled

## 📚 Related Documentation

- [Docker Compose Production Deployment](../fastapi-production-deployment-docker-compose.md)
- [Kubernetes Deployment](../fastapi-kubernetes-deployment.md)
- [Secrets Management](../security/secrets_management.md)
- [Security Guide](../security.md)