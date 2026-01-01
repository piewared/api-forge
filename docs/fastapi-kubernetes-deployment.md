# FastAPI Kubernetes Deployment with Helm

Deploy your FastAPI application to Kubernetes with this comprehensive guide for API Forge. Learn how to use the included Helm chart to deploy PostgreSQL, Redis, Temporal, and your FastAPI app to production Kubernetes clusters with proper secrets management, TLS encryption, and health checks.

## Overview

API Forge provides a production-ready Helm chart for deploying your complete FastAPI stack to Kubernetes. This FastAPI Kubernetes deployment includes:

- **FastAPI Application** - Containerized app with health checks and auto-scaling
- **Temporal Worker** - Distributed workflow processing
- **PostgreSQL** - Production database with TLS and mTLS
- **Redis** - Caching and session storage with TLS (optional via config.yaml)
- **Temporal Server** - Workflow orchestration (optional via config.yaml)
- **Kubernetes Secrets** - Secure credential management
- **NetworkPolicies** - Service-to-service security
- **ConfigMaps** - Environment-specific configuration

The Helm chart automatically synchronizes with your `config.yaml` to enable/disable services (Redis, Temporal) and provides a single-command deployment experience.

## Prerequisites

Before deploying to Kubernetes, ensure you have:

- **Kubernetes Cluster** - v1.24+ (Minikube, GKE, EKS, AKS, or on-prem)
- **kubectl** - Configured and connected to your cluster
- **Helm** - v3.0+ (required for deployment)
- **Docker** - For building images
- **Image Registry** - Docker Hub, GCR, ECR, or private registry (Minikube can use local images)

## Quick Start

Deploy the entire stack with the CLI (recommended):

```bash
# Deploy to Kubernetes using Helm
uv run api-forge-cli deploy up k8s

# Check deployment status
kubectl get pods -n api-forge-prod

# Get application URL
kubectl get svc -n api-forge-prod app
```

Access your FastAPI application:
```bash
kubectl port-forward -n api-forge-prod svc/app 8000:8000
open http://localhost:8000/docs
```

**What the CLI does automatically:**
1. Synchronizes `config.yaml` settings (redis.enabled, temporal.enabled) to Helm `values.yaml`
2. Builds Docker images if needed (or uses existing Minikube images)
3. Generates secrets and certificates (if not already created)
4. Creates namespace via Helm
5. Creates Kubernetes secrets from generated files using `infra/helm/api-forge/scripts/apply-secrets.sh`
6. Packages and deploys the Helm chart with all resources
7. Runs initialization jobs (postgres-verifier, temporal schema setup)
8. Forces pod recreation via timestamp annotations to ensure latest code
9. Waits for services to be ready and validates deployment

For manual deployment or customization using Helm commands directly, see the detailed sections below.

## Project Structure

Kubernetes deployment is managed with Helm under `infra/helm/`:

```
infra/helm/api-forge/
├── Chart.yaml                    # Helm chart metadata
├── values.yaml                   # Default configuration values
├── templates/                    # Kubernetes resource templates
│   ├── namespace.yaml            # Namespace definition
│   ├── configmaps/               # Configuration templates
│   │   ├── app-env.yaml          # App environment ConfigMap
│   │   ├── postgres-config.yaml  # PostgreSQL configuration
│   │   ├── redis-config.yaml     # Redis configuration
│   │   ├── temporal-config.yaml  # Temporal configuration
│   │   └── universal-entrypoint.yaml  # Entrypoint script
│   ├── deployments/              # Deployment templates
│   │   ├── app.yaml              # FastAPI application
│   │   ├── worker.yaml           # Temporal worker
│   │   ├── postgres.yaml         # PostgreSQL database
│   │   ├── redis.yaml            # Redis cache (conditional)
│   │   └── temporal.yaml         # Temporal server (conditional)
│   ├── services/                 # Service templates
│   │   ├── app.yaml
│   │   ├── postgres.yaml
│   │   ├── redis.yaml
│   │   └── temporal.yaml
│   ├── jobs/                     # Initialization job templates
│   │   ├── postgres-verifier.yaml
│   │   ├── temporal-namespace-init.yaml
│   │   └── temporal-schema-setup.yaml
│   ├── persistentvolumeclaims/   # Storage templates
│   │   ├── postgres-data.yaml
│   │   └── redis-data.yaml
│   ├── networkpolicies/          # Security policy templates
│   │   ├── app-netpol.yaml
│   │   └── postgres-netpol.yaml
│   └── _helpers.tpl              # Template helpers
└── scripts/                      # Deployment scripts
    ├── apply-secrets.sh          # Deploy secrets to K8s
    └── build-images.sh           # Build Docker images
```

**Key Features:**
- **Conditional Resources**: Redis and Temporal are deployed only if enabled in `config.yaml`
- **Dynamic Configuration**: ConfigMaps generated from your project's `config.yaml` and `.env`
- **Automatic Sync**: CLI synchronizes settings before each deployment
- **Timestamp Annotations**: Forces pod recreation to ensure latest Docker images

## Database Management

The CLI provides comprehensive database management commands for Kubernetes deployments, supporting both bundled PostgreSQL (deployed in the cluster) and external databases (like Aiven, AWS RDS, Google Cloud SQL).

### Database Setup Commands

```bash
# Initialize database with roles, schemas, and permissions
uv run api-forge-cli k8s db init

# Verify database configuration and test authentication
uv run api-forge-cli k8s db verify

# Synchronize local password files to database (after password changes)
uv run api-forge-cli k8s db sync

# Check database health and performance metrics
uv run api-forge-cli k8s db status

# Create a backup of the database
uv run api-forge-cli k8s db backup

# Reset database to clean state (DESTRUCTIVE - dev/test only)
uv run api-forge-cli k8s db reset
```

### Using External PostgreSQL (Aiven, RDS, Cloud SQL)

To use an external managed PostgreSQL database instead of the bundled one:

1. **Configure the external database**:
   ```bash
   # Using connection string
   uv run api-forge-cli k8s db create --external \
       --connection-string "postgres://admin:secret@db.example.com:5432/mydb?sslmode=require"
   
   # Or using individual parameters
   uv run api-forge-cli k8s db create --external \
       --host db.aivencloud.com --port 20369 \
       --username avnadmin --password secret \
       --database defaultdb --sslmode require
   ```
   
   This command will:
   - Update `.env` with `PRODUCTION_DATABASE_URL`
   - Configure database credentials in `config.yaml`
   - Generate necessary password files in `infra/secrets/keys/`

2. **Initialize the database** (creates roles, schemas, grants permissions):
   ```bash
   uv run api-forge-cli k8s db init
   ```

3. **Verify the setup** (tests connectivity and credentials):
   ```bash
   uv run api-forge-cli k8s db verify
   ```

4. **Deploy** - the application will automatically use the external database:
   ```bash
   uv run api-forge-cli deploy up k8s
   ```

**Important Notes:**
- The `init` command creates application users (`appuser`, `backupuser`, `temporaluser`) and the `app` schema
- The `verify` command now tests password authentication to catch mismatches early
- The `sync` command updates database passwords to match your local secret files
- In production, the app automatically uses `search_path=app` to isolate tables from the `public` schema
- Connection strings preserve existing query parameters (like `?sslmode=require`) while adding production settings

## Deployment Steps

### Step 1: Build Docker Images

**Using the CLI** (included in `deploy up k8s`):

The CLI automatically handles image building and checks for existing images.

**Using the Helm script:**

```bash
# Build all images with the Helm build script
./infra/helm/api-forge/scripts/build-images.sh
```

This builds:
- `api-forge-app:latest` - FastAPI application
- `api-forge-postgres:latest` - PostgreSQL with custom config
- `api-forge-redis:latest` - Redis with TLS support
- `api-forge-temporal:latest` - Temporal server

**For Minikube** (local development):

```bash
# Use Minikube's Docker daemon (no registry push needed)
eval $(minikube docker-env)
./infra/helm/api-forge/scripts/build-images.sh
```

**For production clusters** (requires registry):

```bash
# Build images
./infra/helm/api-forge/scripts/build-images.sh

# Tag for your registry
docker tag api-forge-app:latest your-registry/api-forge-app:v1.0.0
docker tag api-forge-postgres:latest your-registry/api-forge-postgres:v1.0.0
docker tag api-forge-redis:latest your-registry/api-forge-redis:v1.0.0
docker tag api-forge-temporal:latest your-registry/api-forge-temporal:v1.0.0

# Push to registry
docker push your-registry/api-forge-app:v1.0.0
docker push your-registry/api-forge-postgres:v1.0.0
docker push your-registry/api-forge-redis:v1.0.0
docker push your-registry/api-forge-temporal:v1.0.0

# Update values.yaml with registry paths
# Edit infra/helm/api-forge/values.yaml:
# image:
#   app: your-registry/api-forge-app:v1.0.0
#   postgres: your-registry/api-forge-postgres:v1.0.0
```

### Step 2: Generate Secrets and Certificates

**Using the CLI:**

```bash
# The CLI automatically generates secrets on first deployment
uv run api-forge-cli deploy up k8s
```

**Using the script manually:**

```bash
# Generate all secrets and certificates
./infra/secrets/generate_secrets.sh
```

This creates in `infra/secrets/`:
- `keys/postgres_password.txt` - PostgreSQL superuser password
- `keys/postgres_app_user_pw.txt` - Application database user password
- `keys/postgres_app_ro_pw.txt` - Read-only user password
- `keys/postgres_app_owner_pw.txt` - Schema owner password
- `keys/postgres_temporal_pw.txt` - Temporal database user password
- `keys/redis_password.txt` - Redis authentication password
- `keys/session_signing_secret.txt` - Session JWT signing key
- `keys/csrf_signing_secret.txt` - CSRF token signing key
- `keys/oidc_google_client_secret.txt` - Google OAuth client secret
- `keys/oidc_microsoft_client_secret.txt` - Microsoft OAuth client secret
- `keys/oidc_keycloak_client_secret.txt` - Keycloak OAuth client secret
- `certs/ca.crt`, `certs/ca.key` - Certificate Authority for mTLS
- `certs/postgres.crt`, `certs/postgres.key` - PostgreSQL TLS certificate
- `certs/redis.crt`, `certs/redis.key` - Redis TLS certificate

**Note**: The script is idempotent and will not overwrite existing secrets.

### Step 3: Create Namespace

**Using the CLI:**

```bash
# The CLI creates the namespace automatically via Helm
uv run api-forge-cli deploy up k8s
```

**Manual alternative with Helm:**

```bash
# The namespace is created by the Helm chart
# Configured in infra/helm/api-forge/values.yaml:
#   namespace: api-forge-prod

# Or create manually if needed
kubectl create namespace api-forge-prod
```

### Step 4: Create Kubernetes Secrets

**Using the CLI:**

```bash
# The CLI creates all secrets from generated files automatically
uv run api-forge-cli deploy up k8s
```

**Using the Helm script:**

```bash
# Deploy all secrets to your namespace
./infra/helm/api-forge/scripts/apply-secrets.sh
```

This script reads all secret files from `infra/secrets/keys/` and `infra/secrets/certs/`, then creates or updates the following Kubernetes secrets in the `api-forge-prod` namespace:

- `postgres-secrets` - Database passwords for all users
- `postgres-tls` - PostgreSQL TLS certificate and key
- `postgres-ca` - Certificate Authority for client verification
- `redis-secrets` - Redis authentication password
- `redis-tls` - Redis TLS certificate and key
- `app-secrets` - Session/CSRF signing keys and OIDC client secrets

**Manual alternative:**

```bash
# Set namespace
NAMESPACE=api-forge-prod

# PostgreSQL secrets
kubectl create secret generic postgres-secrets \
  --from-file=postgres_password=infra/secrets/keys/postgres_password.txt \
  --from-file=postgres_app_user_pw=infra/secrets/keys/postgres_app_user_pw.txt \
  --from-file=postgres_app_ro_pw=infra/secrets/keys/postgres_app_ro_pw.txt \
  --from-file=postgres_app_owner_pw=infra/secrets/keys/postgres_app_owner_pw.txt \
  --from-file=postgres_temporal_pw=infra/secrets/keys/postgres_temporal_pw.txt \
  -n $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# PostgreSQL TLS
kubectl create secret tls postgres-tls \
  --cert=infra/secrets/certs/postgres.crt \
  --key=infra/secrets/certs/postgres.key \
  -n $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# PostgreSQL CA
kubectl create secret generic postgres-ca \
  --from-file=ca.crt=infra/secrets/certs/ca.crt \
  -n $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Redis secrets
kubectl create secret generic redis-secrets \
  --from-file=redis_password=infra/secrets/keys/redis_password.txt \
  -n $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Redis TLS
kubectl create secret tls redis-tls \
  --cert=infra/secrets/certs/redis.crt \
  --key=infra/secrets/certs/redis.key \
  -n $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Application secrets
kubectl create secret generic app-secrets \
  --from-file=session_signing_secret=infra/secrets/keys/session_signing_secret.txt \
  --from-file=csrf_signing_secret=infra/secrets/keys/csrf_signing_secret.txt \
  --from-file=oidc_google_client_secret=infra/secrets/keys/oidc_google_client_secret.txt \
  --from-file=oidc_microsoft_client_secret=infra/secrets/keys/oidc_microsoft_client_secret.txt \
  --from-file=oidc_keycloak_client_secret=infra/secrets/keys/oidc_keycloak_client_secret.txt \
  -n $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
```

**Using External Secrets Operator** (production recommendation):

For production, use [External Secrets Operator](https://external-secrets.io/) to sync secrets from cloud providers:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-secrets
  namespace: api-forge-prod
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: SecretStore
  target:
    name: app-secrets
  data:
    - secretKey: session_signing_secret
      remoteRef:
        key: api-forge/session-secret
    - secretKey: csrf_signing_secret
      remoteRef:
        key: api-forge/csrf-secret
    - secretKey: oidc_google_client_secret
      remoteRef:
        key: api-forge/google-client-secret
```

### Step 5: Deploy with Helm

**Using the CLI (recommended):**

```bash
# Deploy everything with one command
uv run api-forge-cli deploy up k8s

# The CLI performs these steps:
# 1. Syncs config.yaml → values.yaml (redis.enabled, temporal.enabled)
# 2. Builds/checks Docker images
# 3. Generates secrets if needed
# 4. Applies secrets via script
# 5. Packages Helm chart
# 6. Installs/upgrades Helm release
# 7. Monitors deployment status
```

**Manual Helm deployment:**

```bash
# Navigate to Helm chart directory
cd infra/helm/api-forge

# Package the chart
helm package .

# Install the chart
helm install api-forge ./api-forge-0.1.0.tgz \
  --namespace api-forge-prod \
  --create-namespace

# Or upgrade if already installed
helm upgrade api-forge ./api-forge-0.1.0.tgz \
  --namespace api-forge-prod \
  --install

# Check release status
helm list -n api-forge-prod
helm status api-forge -n api-forge-prod
```

**Customizing with values.yaml:**

```bash
# Create custom values file
cat > custom-values.yaml <<EOF
redis:
  enabled: false  # Disable Redis deployment

app:
  replicaCount: 3  # Scale to 3 replicas

image:
  pullPolicy: Always  # Always pull latest images
EOF

# Deploy with custom values
helm install api-forge ./infra/helm/api-forge \
  --namespace api-forge-prod \
  --create-namespace \
  --values custom-values.yaml

# Or override specific values via CLI
helm install api-forge ./infra/helm/api-forge \
  --namespace api-forge-prod \
  --set redis.enabled=false \
  --set app.replicaCount=3
```

### Step 6: Verify Deployment

**Check Helm release:**

```bash
# Using the CLI (recommended)
uv run api-forge-cli deploy status k8s
uv run api-forge-cli deploy history

# Or using Helm directly
helm list -n api-forge-prod
helm status api-forge -n api-forge-prod

# View deployed resources
helm get manifest api-forge -n api-forge-prod
```

**Check Kubernetes resources:**

```bash
# Get all resources in namespace
kubectl get all -n api-forge-prod

# Check specific resource types
kubectl get pods -n api-forge-prod
kubectl get services -n api-forge-prod
kubectl get deployments -n api-forge-prod
kubectl get jobs -n api-forge-prod
kubectl get pvc -n api-forge-prod

# Check resource details
kubectl describe deployment app -n api-forge-prod
kubectl describe service app -n api-forge-prod
```

### Step 7: Monitor Initialization Jobs

**Check job status:**

```bash
# List all jobs
kubectl get jobs -n api-forge-prod

# Check specific jobs
kubectl get job postgres-verifier -n api-forge-prod
kubectl get job temporal-namespace-init -n api-forge-prod
kubectl get job temporal-schema-setup -n api-forge-prod

# Wait for job completion
kubectl wait --for=condition=complete job/postgres-verifier \
  -n api-forge-prod --timeout=300s

# View job logs
kubectl logs -n api-forge-prod job/postgres-verifier
kubectl logs -n api-forge-prod job/temporal-namespace-init
kubectl logs -n api-forge-prod job/temporal-schema-setup
```

**Jobs run automatically** after Helm deployment and perform these tasks:

1. **postgres-verifier**: Validates PostgreSQL TLS certificates and permissions
2. **temporal-namespace-init**: Creates Temporal namespace
3. **temporal-schema-setup**: Initializes Temporal database schemas

**Rerun jobs if needed:**

```bash
# Delete and recreate a job (jobs are immutable)
kubectl delete job postgres-verifier -n api-forge-prod
helm upgrade api-forge ./infra/helm/api-forge -n api-forge-prod

# Or redeploy with CLI
uv run api-forge-cli deploy up k8s
```

### Step 8: Test Application

**Port forward to access the application:**

```bash
# Forward application port
kubectl port-forward -n api-forge-prod svc/app 8000:8000

# In another terminal, test health endpoints
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/health

# Access FastAPI documentation
open http://localhost:8000/docs
```

**View application logs:**

```bash
# Application logs
kubectl logs -n api-forge-prod -l app.kubernetes.io/name=app --tail=100 -f

# Worker logs
kubectl logs -n api-forge-prod -l app.kubernetes.io/name=worker --tail=100 -f

# PostgreSQL logs
kubectl logs -n api-forge-prod -l app.kubernetes.io/name=postgres --tail=100

# Redis logs (if enabled)
kubectl logs -n api-forge-prod -l app.kubernetes.io/name=redis --tail=100

# Temporal logs (if enabled)
kubectl logs -n api-forge-prod -l app.kubernetes.io/name=temporal --tail=100
```

**Exec into containers for debugging:**

```bash
# Shell into app container
kubectl exec -it -n api-forge-prod deployment/app -- /bin/bash

# Test database connection
kubectl exec -it -n api-forge-prod deployment/app -- \
  psql -h postgres -U appuser -d appdb -c "SELECT version();"

# Test Redis connection (if enabled)
kubectl exec -it -n api-forge-prod deployment/redis -- redis-cli ping
```

## Configuration

### Helm Values

Configuration is managed through Helm's `values.yaml` file located at `infra/helm/api-forge/values.yaml`.

**Key configuration sections:**

```yaml
# Namespace
namespace: api-forge-prod

# Image configuration
image:
  app: api-forge-app:latest
  postgres: api-forge-postgres:latest
  redis: api-forge-redis:latest
  temporal: api-forge-temporal:latest
  pullPolicy: IfNotPresent  # Use 'Always' for production registries

# Replica counts
app:
  replicaCount: 1
worker:
  replicaCount: 1

# Service enablement (synced from config.yaml)
redis:
  enabled: true
temporal:
  enabled: true

# Resource limits
resources:
  app:
    requests:
      memory: "256Mi"
      cpu: "250m"
    limits:
      memory: "512Mi"
      cpu: "1000m"
```

### Config Sync Feature

The CLI automatically synchronizes settings from `config.yaml` to `values.yaml` before each deployment:

**Synced settings:**
- `config.redis.enabled` → `redis.enabled` in values.yaml
- `config.temporal.enabled` → `temporal.enabled` in values.yaml

This ensures your Kubernetes deployment matches your application configuration.

**How it works:**

```bash
# When you run:
uv run api-forge-cli deploy up k8s

# The CLI:
# 1. Reads config.yaml
# 2. Updates values.yaml with redis.enabled and temporal.enabled
# 3. Reports synced changes
# 4. Proceeds with Helm deployment
```

### Customizing Deployment

**Option 1: Modify values.yaml directly**

```bash
# Edit the values file
vim infra/helm/api-forge/values.yaml

# Deploy changes
uv run api-forge-cli deploy up k8s
# Or manually:
helm upgrade api-forge ./infra/helm/api-forge -n api-forge-prod
```

**Option 2: Create custom values file**

```bash
# Create custom overrides
cat > custom-values.yaml <<EOF
app:
  replicaCount: 3
redis:
  enabled: false
resources:
  app:
    requests:
      memory: "512Mi"
      cpu: "500m"
EOF

# Deploy with custom values
helm upgrade api-forge ./infra/helm/api-forge \
  -n api-forge-prod \
  --values custom-values.yaml
```

**Option 3: Override via CLI flags**

```bash
# Override specific values
helm upgrade api-forge ./infra/helm/api-forge \
  -n api-forge-prod \
  --set app.replicaCount=3 \
  --set redis.enabled=false
```

### ConfigMaps

Helm templates create ConfigMaps dynamically from your project files:

- **app-env** - Environment variables from `.env` and `config.yaml`
- **postgres-config** - PostgreSQL configuration files
- **redis-config** - Redis configuration
- **temporal-config** - Temporal configuration
- **universal-entrypoint** - Container entrypoint script

**Updating ConfigMaps:**

```bash
# Update config.yaml or .env locally
vim config.yaml

# Redeploy with Helm (ConfigMaps are recreated)
helm upgrade api-forge ./infra/helm/api-forge -n api-forge-prod

# Or use CLI
uv run api-forge-cli deploy up k8s

# Restart pods to pick up changes (forced by timestamp annotation)
# Pods automatically restart on each deployment
```

## Health Checks

### Liveness Probes

Kubernetes automatically restarts unhealthy pods:

```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 8000
  initialDelaySeconds: 60
  periodSeconds: 30
  timeoutSeconds: 10
  failureThreshold: 3
```

### Readiness Probes

Kubernetes only routes traffic to ready pods:

```yaml
readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 15
  timeoutSeconds: 10
  failureThreshold: 3
```

### Health Endpoints

API Forge provides comprehensive health endpoints:

- **`/health/live`** - Simple liveness check (returns 200 if app is running)
- **`/health/ready`** - Readiness check (validates database, Redis, Temporal connections)
- **`/health`** - Detailed health status with metrics

## Resource Management

### Resource Requests and Limits

Resource configuration is managed through `values.yaml`. The templates dynamically read these values:

```yaml
# infra/helm/api-forge/values.yaml
app:
  resources:
    requests:
      cpu: 250m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi
```

**Production Sizing Guidelines**:

| Component | Requests (CPU/Mem) | Limits (CPU/Mem) | Notes |
|-----------|-------------------|------------------|-------|
| App | 250m / 256Mi | 1000m / 1Gi | Scale horizontally with HPA |
| Worker | 250m / 256Mi | 1000m / 1Gi | Conservative scale-down for workflows |
| PostgreSQL | 500m / 1Gi | 2000m / 4Gi | Consider managed DB for HA |
| Redis | 250m / 256Mi | 1000m / 1Gi | Match maxMemory config |
| Temporal | 500m / 1Gi | 2000m / 4Gi | Single instance sufficient for most loads |

### Horizontal Pod Autoscaling (HPA)

The Helm chart includes built-in HPA support for the app and worker deployments. Enable autoscaling in `values.yaml`:

```yaml
# infra/helm/api-forge/values.yaml
app:
  replicas: 1  # Base replicas when HPA is disabled
  autoscaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 5
    targetCPUUtilizationPercentage: 70
    targetMemoryUtilizationPercentage: 80
    behavior:
      scaleDown:
        stabilizationWindowSeconds: 300  # Wait 5 min before scaling down
        percentValue: 10                  # Scale down 10% at a time
        periodSeconds: 60
      scaleUp:
        stabilizationWindowSeconds: 0    # Scale up immediately
        percentValue: 100
        podsValue: 4                      # Add up to 4 pods at once
        periodSeconds: 15

worker:
  autoscaling:
    enabled: true
    minReplicas: 1
    maxReplicas: 5
    behavior:
      scaleDown:
        stabilizationWindowSeconds: 600  # Workers scale down more conservatively
        periodSeconds: 120               # to avoid disrupting running workflows
```

When `autoscaling.enabled: true`, the HPA controller manages replica count automatically based on CPU/memory metrics.

**Check HPA status:**
```bash
kubectl get hpa -n api-forge-prod
kubectl describe hpa app -n api-forge-prod
```

### Pod Disruption Budgets (PDB)

PDBs ensure service availability during voluntary disruptions (node drains, upgrades). The chart includes PDBs for all services:

```yaml
# infra/helm/api-forge/values.yaml
app:
  podDisruptionBudget:
    enabled: true
    maxUnavailable: 1   # Allow 1 pod to be unavailable (works with any replica count)
    # Or use minAvailable (but blocks eviction when replicas=1):
    # minAvailable: 1

postgres:
  podDisruptionBudget:
    enabled: true
    maxUnavailable: 1

redis:
  podDisruptionBudget:
    enabled: true
    maxUnavailable: 1
```

> **Note:** Use `maxUnavailable` instead of `minAvailable` when running single-replica deployments. With `minAvailable: 1` and only 1 replica, Kubernetes cannot evict the pod during voluntary disruptions (node drains, upgrades), causing a deadlock.

**Check PDB status:**
```bash
kubectl get pdb -n api-forge-prod
kubectl describe pdb app -n api-forge-prod
```

### Manual Horizontal Pod Autoscaling

If you prefer manual HPA configuration or need custom metrics:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: app
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
```

## Networking

### Services

**ClusterIP** (internal only):
```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres
spec:
  type: ClusterIP
  ports:
    - port: 5432
      targetPort: 5432
  selector:
    app: postgres
```

**LoadBalancer** (external access):
```yaml
apiVersion: v1
kind: Service
metadata:
  name: app
spec:
  type: LoadBalancer
  ports:
    - port: 80
      targetPort: 8000
  selector:
    app: app
```

### Ingress

API Forge includes built-in Ingress support via CLI flags. Enable external access with:

```bash
# Basic ingress (HTTP)
uv run api-forge-cli deploy up k8s --ingress

# Custom hostname with TLS
uv run api-forge-cli deploy up k8s --ingress --ingress-host api.example.com --ingress-tls-secret api-tls
```

For comprehensive Ingress documentation including TLS setup, cloud provider configurations, and troubleshooting, see the **[Ingress Configuration Guide](./fastapi-kubernetes-ingress.md)**.

### NetworkPolicies

Restrict pod-to-pod communication:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: app-netpol
spec:
  podSelector:
    matchLabels:
      app: app
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
      ports:
        - protocol: TCP
          port: 8000
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: postgres
      ports:
        - protocol: TCP
          port: 5432
    - to:
        - podSelector:
            matchLabels:
              app: redis
      ports:
        - protocol: TCP
          port: 6379
```

## Storage

### PersistentVolumeClaims

Request persistent storage for databases:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: standard
  resources:
    requests:
      storage: 10Gi
```

Mount in deployments:

```yaml
volumeMounts:
  - name: data
    mountPath: /var/lib/postgresql/data
volumes:
  - name: data
    persistentVolumeClaim:
      claimName: postgres-data
```

### Storage Classes

Use appropriate storage classes for your cloud provider:

- **AWS**: `gp3` (General Purpose SSD)
- **GCP**: `standard-rwo` (Standard persistent disk)
- **Azure**: `managed-premium` (Premium SSD)

## Monitoring

### Logging

View logs for troubleshooting:

```bash
# Application logs
kubectl logs -n my-project-prod deployment/app --tail=100

# Worker logs
kubectl logs -n my-project-prod deployment/worker --tail=100

# PostgreSQL logs
kubectl logs -n my-project-prod deployment/postgres --tail=100

# Follow logs in real-time
kubectl logs -n my-project-prod deployment/app -f
```

### Metrics

Expose Prometheus metrics:

```python
# In your FastAPI app
from prometheus_client import make_asgi_app

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

### Service Monitor

If using Prometheus Operator:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: app-metrics
spec:
  selector:
    matchLabels:
      app: app
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

## Rollback and Recovery

API Forge provides built-in rollback capabilities using Helm's native release management. If a deployment fails or introduces issues, you can quickly restore to a previous working state.

### View Release History

Check the revision history to see all deployments:

```bash
# Using the CLI (recommended)
uv run api-forge-cli deploy history

# Or using Helm directly
helm history api-forge -n api-forge-prod
```

Example output:
```
📜 Release History: api-forge
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ Revision ┃ Updated             ┃ Status     ┃ Chart              ┃ Description         ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│        3 │ 2025-12-02 22:30:00 │ deployed   │ api-forge-0.1.0    │ Upgrade complete    │
│        2 │ 2025-12-02 20:00:00 │ superseded │ api-forge-0.1.0    │ Upgrade complete    │
│        1 │ 2025-12-01 10:00:00 │ superseded │ api-forge-0.1.0    │ Install complete    │
└──────────┴─────────────────────┴────────────┴────────────────────┴─────────────────────┘
```

### Rollback to Previous Revision

Restore to the immediately previous working version:

```bash
# Using the CLI (recommended)
uv run api-forge-cli deploy rollback

# Skip confirmation prompt (for automation)
uv run api-forge-cli deploy rollback --yes

# Using Helm directly
helm rollback api-forge -n api-forge-prod
```

### Rollback to Specific Revision

Restore to a specific revision number:

```bash
# Using the CLI
uv run api-forge-cli deploy rollback 2

# Using Helm directly
helm rollback api-forge 2 -n api-forge-prod
```

### Automatic Rollback on Failure

The deployment automatically rolls back if pods fail to start. This is enabled by the `--rollback-on-failure` flag in Helm upgrade:

```bash
# The CLI does this automatically, but for manual deployments:
helm upgrade --install api-forge ./infra/helm/api-forge \
  --namespace api-forge-prod \
  --wait \
  --rollback-on-failure
```

### Recovery Workflow

When a deployment fails or causes issues:

1. **Check current status**:
   ```bash
   uv run api-forge-cli deploy status k8s
   kubectl get pods -n api-forge-prod
   ```

2. **View release history**:
   ```bash
   uv run api-forge-cli deploy history
   ```

3. **Identify a working revision** from the history table

4. **Rollback to the working revision**:
   ```bash
   uv run api-forge-cli deploy rollback <revision>
   ```

5. **Verify the rollback succeeded**:
   ```bash
   uv run api-forge-cli deploy status k8s
   kubectl get pods -n api-forge-prod
   ```

### ReplicaSet History

Kubernetes also maintains ReplicaSet history for quick pod rollbacks:

```bash
# View deployment rollout history
kubectl rollout history deployment/app -n api-forge-prod

# Rollback to previous ReplicaSet
kubectl rollout undo deployment/app -n api-forge-prod

# Rollback to specific revision
kubectl rollout undo deployment/app -n api-forge-prod --to-revision=2
```

> **Note:** The `revisionHistoryLimit` setting in `values.yaml` controls how many old ReplicaSets are retained. Default is 3.

## Troubleshooting

### Pods Not Starting

**Check pod status**:
```bash
kubectl get pods -n my-project-prod
kubectl describe pod -n my-project-prod <pod-name>
```

**Common issues**:
- **ImagePullBackOff**: Image doesn't exist or registry auth missing
- **CrashLoopBackOff**: Application crashes on startup
- **Pending**: Insufficient resources or PVC not bound

### Database Connection Failures

**Verify PostgreSQL is running**:
```bash
kubectl get pods -n my-project-prod -l app=postgres
kubectl logs -n my-project-prod deployment/postgres
```

**Test connection from app pod**:
```bash
kubectl exec -n my-project-prod deployment/app -- \
  psql -h postgres -U appuser -d appdb -c "SELECT 1;"
```

### Service Not Accessible

**Check service**:
```bash
kubectl get svc -n my-project-prod
kubectl describe svc -n my-project-prod app
```

**Check endpoints**:
```bash
kubectl get endpoints -n my-project-prod app
```

**Port forward for testing**:
```bash
kubectl port-forward -n my-project-prod svc/app 8000:8000
curl http://localhost:8000/health
```

## CI/CD Integration

### GitHub Actions with Helm

```yaml
name: Deploy to Kubernetes with Helm

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Install Helm
        uses: azure/setup-helm@v3
        with:
          version: 'v3.13.0'
      
      - name: Build and push Docker images
        run: |
          docker build -t ${{ secrets.REGISTRY }}/api-forge-app:${{ github.sha }} .
          docker push ${{ secrets.REGISTRY }}/api-forge-app:${{ github.sha }}
          # Build other images as needed
      
      - name: Configure kubectl
        uses: azure/k8s-set-context@v3
        with:
          kubeconfig: ${{ secrets.KUBECONFIG }}
      
      - name: Deploy secrets
        run: |
          # Ensure secrets exist (idempotent)
          ./infra/helm/api-forge/scripts/apply-secrets.sh
        env:
          # Secrets should be stored in GitHub Secrets
          POSTGRES_PASSWORD: ${{ secrets.POSTGRES_PASSWORD }}
          SESSION_SECRET: ${{ secrets.SESSION_SECRET }}
      
      - name: Deploy with Helm
        run: |
          helm upgrade api-forge ./infra/helm/api-forge \
            --install \
            --namespace api-forge-prod \
            --create-namespace \
            --set image.app=${{ secrets.REGISTRY }}/api-forge-app:${{ github.sha }} \
            --set image.pullPolicy=Always \
            --wait \
            --timeout 10m
      
      - name: Verify deployment
        run: |
          helm status api-forge -n api-forge-prod
          kubectl get pods -n api-forge-prod
          kubectl rollout status deployment/app -n api-forge-prod
```

### GitLab CI with Helm

```yaml
deploy:
  stage: deploy
  image: alpine/helm:3.13.0
  script:
    # Configure kubectl
    - kubectl config set-cluster k8s --server="$K8S_SERVER"
    - kubectl config set-credentials gitlab --token="$K8S_TOKEN"
    - kubectl config set-context default --cluster=k8s --user=gitlab
    - kubectl config use-context default
    
    # Build images (if using GitLab registry)
    - docker build -t $CI_REGISTRY_IMAGE/app:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE/app:$CI_COMMIT_SHA
    
    # Deploy secrets
    - ./infra/helm/api-forge/scripts/apply-secrets.sh
    
    # Deploy with Helm
    - helm upgrade api-forge ./infra/helm/api-forge
        --install
        --namespace api-forge-prod
        --create-namespace
        --set image.app=$CI_REGISTRY_IMAGE/app:$CI_COMMIT_SHA
        --wait
        --timeout 10m
    
    # Verify
    - helm status api-forge -n api-forge-prod
    - kubectl rollout status deployment/app -n api-forge-prod
  only:
    - main

### ArgoCD GitOps

For GitOps-style deployments with ArgoCD:

```yaml
# argocd-application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: api-forge
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/your-repo
    targetRevision: main
    path: infra/helm/api-forge
    helm:
      valueFiles:
        - values.yaml
      parameters:
        - name: image.app
          value: your-registry/api-forge-app:v1.0.0
        - name: app.replicaCount
          value: "3"
  destination:
    server: https://kubernetes.default.svc
    namespace: api-forge-prod
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

Deploy ArgoCD application:

```bash
kubectl apply -f argocd-application.yaml
```

## Best Practices

1. **Use Helm for deployments** - Provides templating, versioning, and rollback capabilities
2. **Sync config.yaml settings** - Let the CLI handle redis.enabled and temporal.enabled synchronization
3. **Set resource requests and limits** - Configure in `values.yaml` for all containers
4. **Enable HPA for production** - Set `app.autoscaling.enabled: true` for automatic scaling
5. **Enable PDBs** - Ensure `podDisruptionBudget.enabled: true` for service availability during maintenance
6. **Implement health checks** - Configure liveness and readiness probes
7. **Use secrets properly** - Never store sensitive data in ConfigMaps or values.yaml
8. **Enable NetworkPolicies** - Restrict pod-to-pod communication
9. **Use Ingress with TLS** - Secure external access with TLS certificates
10. **Use PersistentVolumes** - Ensure data persistence for stateful services
11. **Tag images with versions** - Avoid using `latest` in production
12. **Monitor and log** - Implement comprehensive monitoring and logging
13. **Test locally first** - Use Minikube to test deployments before production
14. **Use External Secrets Operator** - For production secret management
15. **Leverage Helm rollbacks** - Use `deploy rollback` CLI command if issues arise

## Helm-Specific Tips

- **Use `helm diff`** - Preview changes before applying (requires helm-diff plugin)
- **Leverage hooks** - Use Helm hooks for pre/post-install actions
- **Version your charts** - Increment Chart.yaml version for each change
- **Test templates** - Use `helm template` to render templates locally
- **Use `.helmignore`** - Exclude unnecessary files from chart packages

## Related Documentation

- [Ingress Configuration](./fastapi-kubernetes-ingress.md) - External access, TLS, and routing
- [Docker Dev Environment](./fastapi-docker-dev-environment.md) - Local testing before deployment
- [Docker Compose Production](./fastapi-production-deployment-docker-compose.md) - Alternative deployment
- [Testing Strategy](./fastapi-testing-strategy.md) - Test before deploying
- [Secrets Management](./security/secrets_management.md) - Comprehensive secrets guide
- [Helm Migration Plan](./helm-migration-plan-update.md) - Migration from Kustomize to Helm

## Additional Resources

- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Helm Documentation](https://helm.sh/docs/)
- [Helm Best Practices](https://helm.sh/docs/chart_best_practices/)
- [External Secrets Operator](https://external-secrets.io/)
- [cert-manager](https://cert-manager.io/)
- [ArgoCD](https://argo-cd.readthedocs.io/) - GitOps continuous delivery
