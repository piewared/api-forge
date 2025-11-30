# Kubernetes Deployment Workflow Update

## Overview
Updated `k8s_deployer.py` to implement a comprehensive deployment workflow that:
- Eliminates duplicate config file maintenance
- Integrates secret deployment from existing scripts
- Automates config file staging for Helm
- Provides a single-command deployment experience

## New Deployment Workflow

### Command
```bash
uv run api-forge-cli deploy up k8s
```

### Execution Steps

#### 1. **Build Docker Images**
- Runs `helm/api-forge/scripts/build-images.sh`
- Builds all images with `:latest` tags
- Optional: Force rebuild for secret rotation (`--force-recreate`)

#### 2. **Load Images to Minikube**
- Automatically loads 4 images:
  - `api-forge-app:latest`
  - `app_data_postgres_image:latest`
  - `app_data_redis_image:latest`
  - `my-temporal-server:latest`

#### 3. **Deploy Secrets**
- Uses existing `k8s/scripts/apply-secrets.sh`
- Assumes secrets already generated in `infra/secrets/`
- Auto-generates if missing (first-time setup)
- Creates in target namespace:
  - `postgres-secrets`
  - `postgres-tls`
  - `postgres-ca`
  - `redis-secrets`
  - `app-secrets`

#### 4. **Copy Config Files to Helm Staging**
**NEW FEATURE** - Copies files at deployment time:

**From Project Root:**
- `.env` → `helm/api-forge/files/.env`
- `config.yaml` → `helm/api-forge/files/config.yaml`

**From PostgreSQL Configs:**
- `infra/docker/prod/postgres/postgresql.conf` → `files/postgresql.conf`
- `infra/docker/prod/postgres/pg_hba.conf` → `files/pg_hba.conf`
- `infra/docker/prod/postgres/verify-init.sh` → `files/verify-init.sh`
- `infra/docker/prod/postgres/init-scripts/01-init-app.sh` → `files/01-init-app.sh`

**From Scripts:**
- `infra/docker/prod/scripts/universal-entrypoint.sh` → `files/universal-entrypoint.sh`

**From Temporal:**
- `infra/docker/prod/temporal/scripts/schema-setup.sh` → `files/temporal/schema-setup.sh`
- `infra/docker/prod/temporal/scripts/entrypoint.sh` → `files/temporal/entrypoint.sh`
- `infra/docker/prod/temporal/scripts/namespace-init.sh` → `files/temporal/namespace-init.sh`

#### 5. **Helm Deployment**
- Helm reads files from `helm/api-forge/files/`
- Creates ConfigMaps automatically via templates
- Deploys all resources:
  - Namespace
  - Secrets (references pre-created ones)
  - ConfigMaps (from files/)
  - PersistentVolumeClaims
  - Deployments
  - Services
  - NetworkPolicies
  - Jobs

#### 6. **Status Display**
- Shows deployment status
- Lists pods, services, and their health

## Benefits

### 1. **No Duplicate Config Files**
**Before:** Had to manually maintain copies in `helm/api-forge/files/`
**After:** Files automatically synced from source at deployment time

### 2. **Single Source of Truth**
- Edit `.env`, `config.yaml`, etc. in project root
- Changes automatically staged during deployment
- No sync drift between environments

### 3. **Integrated Secret Management**
- Reuses proven `apply-secrets.sh` script
- Automatic secret generation if missing
- Clear error messages if secrets not found

### 4. **Simplified Workflow**
**Before:**
```bash
# Manual steps
./infra/secrets/generate_secrets.sh
./k8s/scripts/apply-secrets.sh
cp .env helm/api-forge/files/
cp config.yaml helm/api-forge/files/
cp infra/docker/prod/postgres/*.conf helm/api-forge/files/
# ... more copies ...
helm install api-forge ./helm/api-forge
```

**After:**
```bash
# Single command
uv run api-forge-cli deploy up k8s
```

## Implementation Details

### New Methods in `k8s_deployer.py`

#### `_deploy_secrets(namespace: str)`
- Calls `k8s/scripts/apply-secrets.sh`
- Ensures secrets exist before Helm deployment
- Helm templates expect these secrets to pre-exist

#### `_copy_config_files()`
- Dynamically copies files from source locations
- Creates `helm/api-forge/files/` structure
- Skips missing files with warnings
- Shows progress for each file

### Helm ConfigMap Integration

Helm templates use `.Files.Get` to embed config files:

```yaml
# helm/api-forge/templates/configmaps/app-config.yaml
data:
  config.yaml: |
    {{- .Files.Get "files/config.yaml" | nindent 4 }}
```

This works because we copy files to `files/` before running Helm.

## Migration Notes

### For Existing Deployments
1. Old duplicated files in `helm/api-forge/files/` can be deleted
2. They'll be regenerated on next deployment
3. Or keep them as fallback (deployer overwrites them)

### For CI/CD Pipelines
Update pipelines to just run:
```bash
uv run api-forge-cli deploy up k8s
```

No need for separate config sync steps.

## Testing

Verify the workflow:
```bash
# Clean slate
helm uninstall api-forge -n api-forge-prod
kubectl delete namespace api-forge-prod

# Full deployment
uv run api-forge-cli deploy up k8s

# Check files were copied
ls -la helm/api-forge/files/

# Check ConfigMaps were created
kubectl get configmaps -n api-forge-prod
kubectl describe configmap app-config -n api-forge-prod
```

## Future Enhancements

1. **Config Validation**: Add schema validation before copying
2. **Diff Display**: Show what config changed since last deployment
3. **Rollback Support**: Keep previous config versions
4. **Environment-Specific**: Support dev/staging/prod config overlays
