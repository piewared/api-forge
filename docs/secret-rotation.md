# Secret Rotation Guide

## Overview

The CLI includes a convenient `rotate` command that automates the entire secret rotation workflow for production and Kubernetes deployments. This command handles secret generation, optional backup, and automatic redeployment.

## Command Usage

```bash
uv run api-forge-cli deploy rotate [ENV] [OPTIONS]
```

### Arguments

- `ENV`: Target environment (`prod` or `k8s`)
  - `dev` is not supported (uses hardcoded test credentials)

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--redeploy` / `--no-redeploy` | `--redeploy` | Automatically redeploy after rotation |
| `--force` / `--no-force` | `--force` | Force overwrite existing secrets |
| `--backup` / `--no-backup` | `--backup` | Backup existing secrets before rotation |
| `--namespace`, `-n` | `api-forge-prod` | Kubernetes namespace (k8s only) |

## Common Workflows

### 1. Full Rotation with Redeploy (Recommended)

This is the standard workflow that rotates secrets and immediately redeploys:

```bash
# For Docker Compose production
uv run api-forge-cli deploy rotate prod

# For Kubernetes
uv run api-forge-cli deploy rotate k8s
```

**What happens:**
1. Backs up existing secrets to timestamped directory
2. Generates 11 new cryptographically secure secrets
3. Rebuilds Docker images (picks up new secrets)
4. Forces container/pod recreation
5. Automatic password sync in PostgreSQL on startup
6. Validates deployment health

**Duration:** ~4-5 minutes

### 2. Rotate Without Immediate Deployment

Useful when you want to rotate secrets during a maintenance window:

```bash
# Rotate secrets only
uv run api-forge-cli deploy rotate prod --no-redeploy

# Later, deploy with new secrets
uv run api-forge-cli deploy up prod --force-recreate
```

### 3. Rotate Without Backup

Skip backup if you're confident or have external backups:

```bash
uv run api-forge-cli deploy rotate prod --no-backup
```

### 4. Test Run (Dry Run Alternative)

Rotate secrets without deploying to verify generation:

```bash
uv run api-forge-cli deploy rotate prod --no-redeploy --no-backup
```

## What Gets Rotated

The following secrets are regenerated during rotation:

### Database Credentials (5 secrets)
- `postgres_password.txt` - PostgreSQL superuser password
- `postgres_app_user_pw.txt` - Application database user
- `postgres_app_ro_pw.txt` - Read-only backup user
- `postgres_app_owner_pw.txt` - Schema owner (no login)
- `postgres_temporal_pw.txt` - Temporal workflow engine user

### Application Secrets (3 secrets)
- `redis_password.txt` - Redis cache password
- `session_signing_secret.txt` - Session token signing key
- `csrf_signing_secret.txt` - CSRF protection secret

### OIDC Secrets (3 secrets)
- `oidc_google_client_secret.txt` - Google OAuth client secret
- `oidc_microsoft_client_secret.txt` - Microsoft OAuth client secret
- `oidc_keycloak_client_secret.txt` - Keycloak OAuth client secret

**Note:** OIDC secrets are loaded from `infra/secrets/user-provided.env` if present. These are deterministic (not randomly generated) because they must match OAuth provider configurations.

## Automatic Password Synchronization

After rotation and redeployment, PostgreSQL passwords are automatically synchronized:

### How It Works

1. **Secret Generation**: New passwords written to `infra/secrets/keys/` directory
2. **Docker/K8s Secrets**: Secrets mounted into postgres container at `/app/keys/`
3. **Container Startup**: `pg-password-sync-wrapper.sh` runs automatically
4. **Sync Process**:
   - Starts PostgreSQL
   - Waits for database to be ready
   - Runs `sync-passwords.sh` script
   - Executes `ALTER ROLE` for all 4 database users
   - Completes startup

### Verification

Check postgres logs to confirm sync:

```bash
# Docker Compose
docker logs app_data_postgres 2>&1 | grep sync

# Kubernetes
kubectl logs -n api-forge-prod -l app.kubernetes.io/name=postgres | grep sync
```

Expected output:
```
[pg-password-sync-wrapper] Running password sync script...
[sync-passwords] Synchronizing Postgres role passwords with secrets...
ALTER ROLE
ALTER ROLE
ALTER ROLE
ALTER ROLE
[sync-passwords] Password synchronization complete.
```

## Security Best Practices

### 1. Backup Management

Backups are stored in `infra/secrets/backups/backup-YYYYMMDD-HHMMSS/`:

```bash
# List recent backups
ls -lh infra/secrets/backups/

# Restore from backup if needed
cp -r infra/secrets/backups/backup-20251123-120000/keys/* infra/secrets/keys/
```

**⚠️ Important:** Backups contain sensitive credentials. Manage them securely:
- Delete old backups after confirming successful rotation
- Never commit backup directories to version control
- Consider encrypted storage for long-term retention

### 2. Rotation Schedule

Recommended rotation frequency:

| Environment | Frequency | Reason |
|-------------|-----------|--------|
| Production | Quarterly | Balance security vs operational overhead |
| Staging | Monthly | Test rotation procedures |
| Development | Never | Uses hardcoded test credentials |

**Trigger immediate rotation if:**
- Suspected credential compromise
- Team member with access leaves
- Compliance requirement
- After security audit

### 3. Zero-Downtime Rotation

For production environments requiring zero downtime:

1. **Blue-Green Deployment**: Rotate in staging, validate, then promote
2. **Kubernetes Only**: Uses rolling updates automatically
3. **Docker Compose**: Brief interruption (~10-30 seconds) during restart

### 4. Validation Checklist

After rotation, verify:

```bash
# 1. Check postgres-verifier passed all checks
kubectl logs -n api-forge-prod job/postgres-verifier --tail=30

# 2. Verify database connectivity
kubectl exec -n api-forge-prod deployment/postgres -- bash -c \
  'PGPASSWORD=$(cat /app/keys/postgres_app_user_pw) psql -U appuser -d appdb -c "SELECT 1"'

# 3. Check application health
kubectl exec -n api-forge-prod deployment/app -- curl -s http://localhost:8000/health

# 4. Verify Redis connectivity
kubectl exec -n api-forge-prod deployment/redis -- redis-cli -a $(cat /run/secrets/redis_password) PING
```

## Troubleshooting

### Issue: Secret generation fails

**Symptom:**
```
[ERROR] Secret generation failed: Command 'generate_secrets.sh' returned non-zero exit status 1
```

**Solutions:**
1. Check dependencies: `openssl`, `base64`, `head`, `/dev/urandom`
2. Verify file permissions: `chmod +x infra/secrets/generate_secrets.sh`
3. Ensure `user-provided.env` exists (copy from example if missing)

### Issue: Deployment hangs after rotation

**Symptom:**
Deployment stuck at "Waiting for PostgreSQL/Redis to be ready..."

**Solutions:**
1. Check if old pods are terminating: `kubectl get pods -n api-forge-prod`
2. Wait for old ReplicaSets to fully terminate
3. Verify no resource constraints: `kubectl describe nodes`
4. Check logs: `kubectl logs -n api-forge-prod deployment/postgres`

### Issue: Database connections fail after rotation

**Symptom:**
Applications can't connect to PostgreSQL after rotation

**Solutions:**
1. Verify password sync completed:
   ```bash
   kubectl logs -n api-forge-prod -l app.kubernetes.io/name=postgres | grep "Password synchronization complete"
   ```
2. Check secret mounts:
   ```bash
   kubectl exec -n api-forge-prod deployment/postgres -- ls -la /app/keys/
   ```
3. Manually trigger sync (if needed):
   ```bash
   kubectl exec -n api-forge-prod deployment/postgres -- /opt/entry/admin-scripts/sync-passwords.sh
   ```

### Issue: OIDC authentication fails

**Symptom:**
OAuth login redirects fail or show "invalid client secret"

**Root Cause:**
OIDC client secrets must match OAuth provider configurations

**Solution:**
1. Update secrets in OAuth provider console (Google, Microsoft, Keycloak)
2. Update `infra/secrets/user-provided.env` with matching secrets:
   ```bash
   OIDC_GOOGLE_CLIENT_SECRET=your-new-secret
   OIDC_MICROSOFT_CLIENT_SECRET=your-new-secret
   OIDC_KEYCLOAK_CLIENT_SECRET=your-new-secret
   ```
3. Re-rotate: `uv run api-forge-cli deploy rotate k8s`

## Advanced Usage

### Custom Namespace Rotation (K8s)

Rotate secrets for a specific namespace:

```bash
uv run api-forge-cli deploy rotate k8s --namespace my-custom-ns
```

### Manual Secret Generation

If you need to generate secrets without CLI:

```bash
cd infra/secrets
./generate_secrets.sh --force
```

Options:
- `--force`: Overwrite existing secrets
- `--backup-only`: Create backup without generating new secrets
- `--verify`: Verify existing secrets meet security requirements
- `--list`: List all secret files and sizes

### Rotation in CI/CD Pipelines

Example GitHub Actions workflow:

```yaml
name: Scheduled Secret Rotation

on:
  schedule:
    - cron: '0 2 1 * *'  # First day of month at 2 AM
  workflow_dispatch:       # Manual trigger

jobs:
  rotate-secrets:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Python & UV
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      
      - name: Install UV
        run: pip install uv
      
      - name: Rotate K8s Secrets
        run: |
          uv run api-forge-cli deploy rotate k8s --force --no-backup
        env:
          KUBECONFIG: ${{ secrets.KUBECONFIG }}
      
      - name: Backup rotated secrets to S3
        run: |
          aws s3 cp infra/secrets/keys/ s3://my-secrets-backup/ --recursive --sse
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

## Related Documentation

- [Secrets Management](./security/secrets_management.md) - Comprehensive secrets management guide
- [PostgreSQL Security](./postgres/security.md) - Database security configuration
- [Production Deployment](./fastapi-production-deployment-docker-compose.md) - Full production setup
- [Kubernetes Deployment](./fastapi-kubernetes-deployment.md) - K8s deployment guide

## Summary

The `deploy rotate` command provides a production-ready secret rotation workflow:

✅ **Automated**: Single command handles entire rotation process  
✅ **Safe**: Automatic backups prevent accidental data loss  
✅ **Zero Config**: Password sync happens automatically on container startup  
✅ **Validated**: Built-in health checks verify successful rotation  
✅ **Flexible**: Support for both Docker Compose and Kubernetes  

**Most Common Usage:**
```bash
# Rotate and redeploy - that's it!
uv run api-forge-cli deploy rotate k8s
```
