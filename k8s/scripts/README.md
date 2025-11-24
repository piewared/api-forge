# Kubernetes Automation Scripts

This directory contains automation scripts for building, deploying, and managing the Kubernetes resources.

## Scripts Overview

| Script | Purpose | Usage |
|--------|---------|-------|
| `build-images.sh` | Build all Docker images | `./build-images.sh` |
| `apply-secrets.sh` | Apply Kubernetes secrets | `./apply-secrets.sh [namespace]` |
| `sync-postgres-passwords.sh` | Update Postgres role passwords with latest secrets | `./sync-postgres-passwords.sh [namespace]` |
| `deploy-config.sh` | Sync config files and deploy | `./deploy-config.sh [--restart] [--sync-only]` |
| `deploy-resources.sh` | Deploy all resources | `./deploy-resources.sh [namespace]` |

## Quick Start

For a complete fresh deployment:

```bash
# 1. Build images
./build-images.sh

# 2. Generate secrets (from project root)
cd ../../infra/secrets && ./generate_secrets.sh && cd -

# 3. Sync config files
./deploy-config.sh --sync-only

# 4. Apply Kubernetes secrets (generated + user-provided)
cp ../../infra/secrets/user-provided.env.example ../../infra/secrets/user-provided.env  # first time only
# Fill in values, then run:
./apply-secrets.sh

# 5. Deploy everything
./deploy-resources.sh
```

## Script Details

### deploy-config.sh

Syncs configuration files from source locations to Kubernetes and auto-generates ConfigMaps.

**Requirements**:
- kubectl installed and configured
- Kubernetes cluster accessible
- Source files exist (`.env`, `config.yaml`, postgres configs, temporal scripts)

**Arguments**:
- `--restart` - Also restart app deployment after config update
- `--sync-only` - Only copy files to `.k8s-sources/`, don't deploy

**What it does**:
1. Copies all config files to `k8s/base/.k8s-sources/` with `.k8s` extension
   - `.env` → `.env.k8s` (forces APP_ENVIRONMENT=production)
   - `config.yaml` → `config.yaml.k8s`
   - PostgreSQL configs → `*.k8s` (modifies pg_hba.conf for K8s)
   - Temporal scripts → `*.k8s`
2. Validates Kustomize configuration
3. Previews ConfigMap changes
4. Deploys to Kubernetes (generates 5 ConfigMaps via Kustomize)
5. Optionally restarts app to pick up changes

**ConfigMaps generated**:
- `app-env` (from `.env.k8s`)
- `app-config` (from `config.yaml.k8s`)
- `postgres-config` (from postgresql.conf, pg_hba.conf, init scripts)
- `postgres-verifier-config` (from verify-init.sh)
- `temporal-config` (from temporal scripts)

**Exit codes**:
- `0` - Success
- `1` - Missing source files or deployment failed

**Examples**:
```bash
# Sync and deploy config
./deploy-config.sh

# Sync, deploy, and restart app
./deploy-config.sh --restart

# Only sync files (don't deploy)
./deploy-config.sh --sync-only
```

---

### build-images.sh

Builds all required Docker images with proper build contexts.

**Requirements**:
- Docker installed and running
- Kubernetes cluster running (Minikube, kind, k3d, or Docker Desktop)

**What it does**:
- Detects your cluster type automatically
- Builds 4 images:
  - `app_data_postgres_image` - PostgreSQL with custom config
  - `app_data_redis_image` - Redis with custom config
  - `my-temporal-server:1.29.0` - Temporal server
  - `api-forge-app:latest` - FastAPI application
- Loads images into cluster (Minikube/kind/k3d)
- Verifies all images exist

**Exit codes**:
- `0` - Success
- `1` - Build failed or images not found

---

### apply-secrets.sh

Applies Kubernetes secrets by combining generated files in `infra/secrets/keys/` + `infra/secrets/certs/` with deterministic values stored in `infra/secrets/user-provided.env`.

**Requirements**:
- kubectl installed and configured
- Kubernetes cluster accessible
- Secrets generated in `infra/secrets/` (run `infra/secrets/generate_secrets.sh` first)
- `infra/secrets/user-provided.env` created from the `.example` template and populated with OIDC client secrets

**Arguments**:
- `[namespace]` - Target namespace (default: `api-forge-prod`)

**What it does**:
- Creates namespace if missing
- Validates the user-provided secrets file is present
- Deletes existing secrets (clean slate)
- Creates 5 secret resources:
   - `postgres-secrets` - Database passwords
   - `postgres-tls` - PostgreSQL TLS certificate **chain** (server cert + intermediates) and key
   - `postgres-ca` - CA bundle plus discrete `root-ca.crt` / `intermediate-ca.crt` files for clients that pin a specific trust anchor
   - `redis-secrets` - Redis password
   - `app-secrets` - Session/CSRF signing secrets + OIDC client secrets from `user-provided.env`
- Verifies all secrets exist

**Exit codes**:
- `0` - Success
- `1` - Prerequisites failed, secret files missing, or creation failed

**Example with custom namespace**:
```bash
./apply-secrets.sh my-app-prod
```

---

### sync-postgres-passwords.sh

Executes the in-container `/opt/entry/admin-scripts/sync-passwords.sh` helper so Postgres roles pick up any newly rotated secrets.

**Requirements**:
- `kubectl` access to the target cluster/namespace
- Existing Postgres pod (skips automatically if none are found)
- Secrets already applied so updated password files exist in the mounted volume

**Arguments**:
- `[namespace]` - Target namespace (default: `api-forge-prod`)

**What it does**:
1. Verifies `kubectl` connectivity
2. Locates the current Postgres pod via labels
3. Waits for the pod to report `Ready`
4. Runs the password sync script inside the pod so the `app`, `readonly`, and `temporal` users match the latest secrets

**Exit codes**:
- `0` - Success or skipped (no pod found)
- `1` - Prerequisites failed or password sync failed

**Example**:
```bash
./sync-postgres-passwords.sh staging
```

---

### deploy-resources.sh

Deploys all Kubernetes resources in dependency order with health checks.

**Requirements**:
- kubectl installed and configured
- Kubernetes cluster accessible
- Docker images built (run `build-images.sh` first)
- Secrets applied (run `apply-secrets.sh` first)

**Arguments**:
- `[namespace]` - Target namespace (default: `api-forge-prod`)

**What it does**:
1. **Checks prerequisites** - kubectl, cluster, secrets
2. **Deploys namespace** - Creates if missing
3. **Deploys storage** - PersistentVolumeClaims
4. **Deploys ConfigMaps** - All configuration files (auto-generated via Kustomize from `.k8s-sources/`)
5. **Deploys Services** - ClusterIP services for all components
6. **Deploys databases** - PostgreSQL and Redis
   - Waits up to 120s for each to be ready
7. **Initializes Temporal** - Runs schema setup job
   - Waits up to 300s for completion
8. **Deploys Temporal** - Temporal server, web UI, and admin tools
   - Waits up to 120s for server to be ready
9. **Deploys application** - FastAPI app and Temporal worker
   - Waits up to 120s for each to be ready
10. **Verifies deployment** - Checks pod status and app health
11. **Displays next steps** - Commands for accessing services

**Exit codes**:
- `0` - Success
- `1` - Prerequisites failed, deployment failed, or health checks failed

**Example with custom namespace**:
```bash
./deploy-resources.sh staging
```

**Output**:
The script provides colored output:
- 🟢 Green - Info messages
- 🔵 Blue - Step progress
- 🟡 Yellow - Warnings
- 🔴 Red - Errors

---

## Troubleshooting

### Images not loading into cluster

**Symptom**: Script says images built successfully but pods show `ImagePullBackOff`

**Solution**:
```bash
# For Minikube, ensure you're using the Minikube Docker daemon
eval $(minikube docker-env)
./build-images.sh

# For kind, images should auto-load. If not, manually load:
kind load docker-image api-forge-app:latest
kind load docker-image my-temporal-server:1.29.0
kind load docker-image app_data_postgres_image
kind load docker-image app_data_redis_image
```

### Secrets not found

**Symptom**: `deploy-resources.sh` fails with "Missing required secrets"

**Solution**:
```bash
# Generate secrets first
cd ../../infra/secrets
./generate_secrets.sh
cd -

# Then apply Kubernetes secrets (after filling infra/secrets/user-provided.env)
./apply-secrets.sh
```

### Deployment timeout

**Symptom**: Script waits forever for a pod to be ready

**Check pod status**:
```bash
kubectl get pods -n api-forge-prod
kubectl describe pod <pod-name> -n api-forge-prod
kubectl logs <pod-name> -n api-forge-prod
```

**Common causes**:
- Image pull failure (wrong imagePullPolicy or missing image)
- Insufficient cluster resources (try `minikube config set memory 8192`)
- Configuration error (check ConfigMaps and Secrets)

### Permission denied running scripts

**Solution**:
```bash
chmod +x *.sh
```

---

## Development

### Adding a new resource

If you add a new Kubernetes resource, update `deploy-resources.sh`:

1. Add the file to the appropriate deployment step function
2. If it's a critical service, add a health check
3. Update the step count in log messages
4. Test the full deployment

### Modifying deployment order

The deployment order is critical:
1. Namespace (must exist first)
2. Storage (needed by stateful workloads)
3. ConfigMaps (needed by all pods)
4. Services (networking layer)
5. Databases (dependencies for other services)
6. Temporal setup (must complete before Temporal)
7. Temporal (dependency for app)
8. Application (final layer)

Do not change this order without thorough testing.

---

## CI/CD Integration

These scripts can be used in CI/CD pipelines:

**GitHub Actions example**:
```yaml
- name: Deploy to Kubernetes
  run: |
    ./k8s/scripts/build-images.sh
   ./k8s/scripts/apply-secrets.sh production
    ./k8s/scripts/deploy-resources.sh production
```

**GitLab CI example**:
```yaml
deploy:
  script:
    - ./k8s/scripts/build-images.sh
   - ./k8s/scripts/apply-secrets.sh production
    - ./k8s/scripts/deploy-resources.sh production
```

---

## See Also

- [../DEPLOYMENT_GUIDE.md](../DEPLOYMENT_GUIDE.md) - Complete deployment documentation
- [../BUILD_CONTEXTS.md](../BUILD_CONTEXTS.md) - Docker build context explanations
- [../LOCAL_TESTING.md](../LOCAL_TESTING.md) - Local testing guide
