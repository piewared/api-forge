# Production Deployment Guide

This guide covers the deployment of the FastAPI application stack to production environments including VPS servers and managed container services like Fly.io.

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
- Domain name configured (for SSL certificates)
- At least 2GB RAM and 20GB storage
- OIDC provider credentials (Google, Microsoft, etc.)

### 1. Clone and Setup
```bash
git clone <your-repo>
cd api-forge3

# Copy and configure environment
cp .env .env.production
nano .env.production  # Update configuration values
```

### 2. Generate Secrets
```bash
# The deployment script handles secret generation
sudo bash deploy/deploy-local.txt secrets
```

### 3. Deploy
```bash
# Full deployment with SSL (replace with your domain/email)
sudo bash deploy/deploy-local.txt deploy yourdomain.com your-email@example.com

# Or deploy without SSL setup
sudo bash deploy/deploy-local.txt deploy
```

### 4. Verify Deployment
```bash
# Check service health
curl https://yourdomain.com/health
curl https://yourdomain.com/ready

# View service logs
docker-compose -f docker-compose.prod.yml logs -f
```

## 🔧 Configuration

### Environment Variables

#### Application Configuration
```env
APP_ENVIRONMENT=production
BASE_URL=https://yourdomain.com
APP_PORT=8000
DATA_PATH=/opt/app/data

# Database
DATABASE_URL=postgresql://appuser:$(cat /opt/app/secrets/postgres_password.txt)@postgres:5432/appdb

# Redis
REDIS_URL=redis://:$(cat /opt/app/secrets/redis_password.txt)@redis:6379/0

# JWT & Sessions
JWT_AUDIENCE=api://default
SESSION_MAX_AGE=3600
SESSION_SIGNING_SECRET_FILE=/opt/app/secrets/session_signing_secret.txt
CSRF_SIGNING_SECRET_FILE=/opt/app/secrets/csrf_signing_secret.txt

# CORS
CLIENT_ORIGIN=https://yourdomain.com
```

#### OIDC Configuration
```env
# Google OAuth
OIDC_GOOGLE_CLIENT_ID=your-google-client-id
OIDC_GOOGLE_CLIENT_SECRET=your-google-client-secret

# Microsoft OAuth
OIDC_MICROSOFT_CLIENT_ID=your-microsoft-client-id
OIDC_MICROSOFT_CLIENT_SECRET=your-microsoft-client-secret
```

### Secret Management
All sensitive data is stored in `/opt/app/secrets/` with restricted permissions:

```bash
# Generated automatically
/opt/app/secrets/postgres_password.txt
/opt/app/secrets/redis_password.txt
/opt/app/secrets/session_signing_secret.txt
/opt/app/secrets/csrf_signing_secret.txt

# Update manually
/opt/app/secrets/oidc_google_client_secret.txt
/opt/app/secrets/oidc_microsoft_client_secret.txt

> For Docker Compose-based deployments, keep deterministic secrets such as `OIDC_*_CLIENT_SECRET`
> inside `infra/secrets/user-provided.env` (copied from the `.example`), which is mounted via
> `env_file`. When deploying directly to servers or Kubernetes, provide these values through your
> secret manager of choice—the application only requires them as environment variables.
```

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
```bash
# Update application
docker-compose -f docker-compose.prod.yml pull app
docker-compose -f docker-compose.prod.yml up -d app

# Update all services
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d
```

### SSL Certificate Renewal
```bash
# Manual renewal
certbot renew

# Automatic renewal is configured via cron
```

### Database Maintenance
```bash
# Connect to database
docker exec -it $(docker ps -q -f name=postgres) psql -U appuser -d appdb

# Run VACUUM and ANALYZE
docker exec $(docker ps -q -f name=postgres) psql -U appuser -d appdb -c "VACUUM ANALYZE;"
```

## 🌐 Deployment Platforms

### VPS Deployment
The included deployment script supports major Linux distributions:
- Ubuntu 20.04+ / Debian 11+
- CentOS 8+ / RHEL 8+
- Automated firewall, SSL, and security setup

### Fly.io Deployment
```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Configure and deploy
fly auth login
fly launch --name your-app-name
fly deploy
```

### Docker Swarm
```bash
# Initialize swarm
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.prod.yml app-stack
```

### Kubernetes
Kubernetes manifests can be generated from the docker-compose file:
```bash
# Using Kompose
kompose convert -f docker-compose.prod.yml
kubectl apply -f .
```

## 🚨 Troubleshooting

### Common Issues

#### Application Won't Start
```bash
# Check logs
docker-compose -f docker-compose.prod.yml logs app

# Verify environment configuration
docker-compose -f docker-compose.prod.yml config

# Check secret files
ls -la /opt/app/secrets/
```

#### Database Connection Issues
```bash
# Check PostgreSQL logs
docker-compose -f docker-compose.prod.yml logs postgres

# Test connection
docker exec -it $(docker ps -q -f name=postgres) pg_isready -U appuser -d appdb

# Verify network connectivity
docker exec $(docker ps -q -f name=app) nc -zv postgres 5432
```

#### Redis Connection Issues
```bash
# Check Redis logs
docker-compose -f docker-compose.prod.yml logs redis

# Test Redis connectivity
docker exec $(docker ps -q -f name=redis) redis-cli ping

# Check authentication
docker exec $(docker ps -q -f name=redis) redis-cli auth your-password ping
```

#### SSL Certificate Issues
```bash
# Check certificate status
certbot certificates

# Test SSL configuration
openssl s_client -connect yourdomain.com:443 -servername yourdomain.com

# Renew certificates
certbot renew --dry-run
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
- [ ] SSL certificate requirements verified
- [ ] Server resources adequate (2GB+ RAM, 20GB+ storage)
- [ ] Backup storage configured

### Post-deployment
- [ ] Health endpoints responding correctly
- [ ] OIDC authentication flows working
- [ ] SSL certificates installed and auto-renewal configured
- [ ] Backup scripts tested and running
- [ ] Monitoring and alerting configured
- [ ] Firewall rules verified
- [ ] Documentation updated with environment-specific details

### Security Audit
- [ ] All services running as non-root users
- [ ] Secrets properly secured with restricted permissions
- [ ] Database connections encrypted
- [ ] API rate limiting functional
- [ ] Security headers properly configured
- [ ] Log files protected and rotated
- [ ] Unnecessary services disabled
- [ ] Regular security updates scheduled