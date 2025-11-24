# FastAPI Kubernetes Deployment

Deploy your FastAPI application to Kubernetes with this comprehensive guide for API Forge. Learn how to use the included Kubernetes manifests to deploy PostgreSQL, Redis, Temporal, and your FastAPI app to production Kubernetes clusters with proper secrets management, TLS encryption, and health checks.

## Overview

API Forge provides production-ready Kubernetes manifests for deploying your complete FastAPI stack to Kubernetes. This FastAPI Kubernetes deployment includes:

- **FastAPI Application** - Containerized app with health checks and auto-scaling
- **Temporal Worker** - Distributed workflow processing
- **PostgreSQL** - Production database with TLS and mTLS
- **Redis** - Caching and session storage with TLS
- **Temporal Server** - Workflow orchestration
- **Kubernetes Secrets** - Secure credential management
- **NetworkPolicies** - Service-to-service security
- **ConfigMaps** - Environment-specific configuration

All manifests follow Kubernetes best practices with proper resource limits, health checks, and security contexts.

## Prerequisites

Before deploying to Kubernetes, ensure you have:

- **Kubernetes Cluster** - v1.24+ (Minikube, GKE, EKS, AKS, or on-prem)
- **kubectl** - Configured and connected to your cluster
- **Docker** - For building images
- **Image Registry** - Docker Hub, GCR, ECR, or private registry
- **Helm** (optional) - For certain dependencies

## Quick Start

Deploy the entire stack with the CLI (recommended):

```bash
# Deploy to Kubernetes
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
1. Checks Docker images (prompts to build if needed)
2. Generates secrets and certificates (if not already created)
3. Creates namespace
4. Creates Kubernetes secrets from generated files
5. Deploys configuration files (config.yaml, .env) as ConfigMaps
6. Applies all Kubernetes resources (PVCs, Services, Deployments, NetworkPolicies)
7. Runs initialization jobs (database setup, schema verification)
8. Waits for services to be ready and validates deployment

For manual deployment or customization using scripts or kubectl, see the detailed sections below.

## Project Structure

Kubernetes manifests are organized under `k8s/`:

```
k8s/
├── base/                        # Base Kustomize configuration
│   ├── kustomization.yaml       # Kustomize entry point
│   ├── namespace.yaml           # Namespace definition
│   ├── configmaps/              # Configuration files
│   │   ├── app-config.yaml
│   │   ├── postgres-config.yaml
│   │   └── redis-config.yaml
│   ├── deployments/             # Deployment manifests
│   │   ├── app.yaml             # FastAPI application
│   │   ├── worker.yaml          # Temporal worker
│   │   ├── postgres.yaml        # PostgreSQL database
│   │   ├── redis.yaml           # Redis cache
│   │   └── temporal.yaml        # Temporal server
│   ├── services/                # Service definitions
│   │   ├── app.yaml
│   │   ├── postgres.yaml
│   │   ├── redis.yaml
│   │   └── temporal.yaml
│   ├── jobs/                    # Initialization jobs
│   │   ├── postgres-verifier.yaml
│   │   └── temporal-schema-setup.yaml
│   ├── persistentvolumeclaims/  # Storage
│   │   ├── postgres-data.yaml
│   │   └── redis-data.yaml
│   └── networkpolicies/         # Security policies
│       ├── app-netpol.yaml
│       └── postgres-netpol.yaml
├── overlays/                    # Environment overlays
│   ├── development/
│   ├── staging/
│   └── production/
└── scripts/                     # Deployment scripts
    ├── build-images.sh
    ├── deploy.sh
    └── cleanup.sh
```

## Deployment Steps

### Step 1: Build and Push Docker Images

**Using the CLI** (included in `deploy up k8s` if images don't exist):

The CLI checks for images and prompts you to build if needed.

**Using the script:**

```bash
# Build all images with the provided script
./k8s/scripts/build-images.sh
```

**Manual alternative:**

```bash
# Build FastAPI application
docker build -t my-project-app:latest -f Dockerfile .

# Build PostgreSQL
docker build -t my-project-postgres:latest -f docker/prod/postgres/Dockerfile .

# Build Redis  
docker build -t my-project-redis:latest -f docker/prod/redis/Dockerfile .

# Build Temporal
docker build -t my-project-temporal:latest -f docker/prod/temporal/Dockerfile .

# Tag images for your registry
docker tag my-project-app:latest your-registry/my-project-app:v1.0.0
docker tag my-project-postgres:latest your-registry/my-project-postgres:v1.0.0

# Push to registry
docker push your-registry/my-project-app:v1.0.0
docker push your-registry/my-project-postgres:v1.0.0

# Update image references in k8s/base/deployments/*.yaml
```

### Step 2: Generate Secrets and Certificates

**Using the CLI:**

```bash
# The CLI automatically generates secrets on first deployment
uv run api-forge-cli deploy up k8s
```

**Using the script:**

```bash
# Generate all secrets and certificates
./infra/secrets/generate_secrets.sh
```

**Manual alternative:**

```bash
# Generate secrets (first time only)
cd infra/secrets
./generate_secrets.sh
```

This creates:
- Database passwords (postgres_password.txt, postgres_app_user_pw.txt, etc.)
- Redis password (redis_password.txt)
- Session signing secrets (session_signing_secret.txt)
- CSRF signing secrets (csrf_signing_secret.txt)
- TLS certificates and keys (postgres.crt, postgres.key, redis.crt, redis.key)
- CA certificates for mTLS (ca.crt, ca.key)
- Deterministic OIDC client secrets captured during the script run (prompts, CLI flags, or
  `--user-secrets-file`) and written to `infra/secrets/keys/oidc_*_client_secret.txt` for reuse.

### Step 3: Create Namespace

**Using the CLI:**

```bash
# The CLI creates the namespace automatically
uv run api-forge-cli deploy up k8s
```

**Manual alternative:**

```bash
kubectl create namespace my-project-prod
```

### Step 4: Create Kubernetes Secrets

**Using the CLI:**

```bash
# The CLI creates all secrets from generated files
uv run api-forge-cli deploy up k8s
```

**Using the script:**

```bash
# After running generate_secrets.sh (interactive prompts or --user-secrets-file),
# apply all generated secrets to your namespace
./k8s/scripts/apply-secrets.sh my-project-prod
```

This script reads every secret under `infra/secrets/keys/` (including the
deterministic OIDC client secret files) plus TLS assets under `infra/secrets/certs/`, then
creates/updates all Kubernetes secrets (`postgres-secrets`, `postgres-tls`, `postgres-ca`,
`redis-secrets`, and `app-secrets`) in the selected namespace.

**Manual alternative:**

```bash
# Create secrets from generated files
kubectl create secret generic postgres-secrets \
  --from-file=postgres_password=infra/secrets/keys/postgres_password.txt \
  --from-file=postgres_app_user_pw=infra/secrets/keys/postgres_app_user_pw.txt \
  --from-file=postgres_app_ro_pw=infra/secrets/keys/postgres_app_ro_pw.txt \
  --from-file=postgres_app_owner_pw=infra/secrets/keys/postgres_app_owner_pw.txt \
  --from-file=postgres_temporal_pw=infra/secrets/keys/postgres_temporal_pw.txt \
  -n my-project-prod

kubectl create secret generic redis-secrets \
  --from-file=redis_password=infra/secrets/keys/redis_password.txt \
  -n my-project-prod

kubectl create secret generic app-secrets \
  --from-file=session_signing_secret=infra/secrets/keys/session_signing_secret.txt \
  --from-file=csrf_signing_secret=infra/secrets/keys/csrf_signing_secret.txt \
  --from-file=oidc_google_client_secret=infra/secrets/keys/oidc_google_client_secret.txt \
  --from-file=oidc_microsoft_client_secret=infra/secrets/keys/oidc_microsoft_client_secret.txt \
  --from-file=oidc_keycloak_client_secret=infra/secrets/keys/oidc_keycloak_client_secret.txt \
  -n my-project-prod

# Create TLS secrets
kubectl create secret tls postgres-tls \
  --cert=infra/secrets/certs/postgres.crt \
  --key=infra/secrets/certs/postgres.key \
  -n my-project-prod

kubectl create secret generic postgres-ca \
  --from-file=ca.crt=infra/secrets/certs/ca.crt \
  -n my-project-prod

kubectl create secret tls redis-tls \
  --cert=infra/secrets/certs/redis.crt \
  --key=infra/secrets/certs/redis.key \
  -n my-project-prod
```

**Using External Secrets Operator** (production recommendation):

For production, use [External Secrets Operator](https://external-secrets.io/) to sync secrets from AWS Secrets Manager, Google Secret Manager, or HashiCorp Vault:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-secrets
  namespace: my-project-prod
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
        key: my-project/session-secret
    - secretKey: csrf_signing_secret
      remoteRef:
        key: my-project/csrf-secret
```

### Step 5: Deploy Configuration as ConfigMaps

**Using the CLI:**

```bash
# The CLI automatically deploys config.yaml and .env as ConfigMaps
uv run api-forge-cli deploy up k8s
```

**Using the script:**

```bash
# Deploy config.yaml, .env, and other configs as ConfigMaps
./k8s/scripts/deploy-config.sh
```

**Manual alternative:**

```bash
# Create ConfigMap from config.yaml
kubectl create configmap app-config \
  --from-file=config.yaml=config.yaml \
  -n my-project-prod

# Create ConfigMap from .env file
kubectl create configmap env-config \
  --from-env-file=.env \
  -n my-project-prod

# Create ConfigMaps for PostgreSQL configuration
kubectl create configmap postgres-config \
  --from-file=postgresql.conf=docker/prod/postgres/postgresql.conf \
  --from-file=pg_hba.conf=docker/prod/postgres/pg_hba.conf \
  -n my-project-prod
```

**Note**: ConfigMaps are created dynamically from your project's configuration files, not from static manifests.

### Step 6: Apply Kubernetes Resources

**Using the CLI:**

```bash
# Deploy all manifests using Kustomize
uv run api-forge-cli deploy up k8s

# Check deployment status
uv run api-forge-cli deploy status k8s
```

**Using the script:**

```bash
# Deploy all Kubernetes resources (PVCs, Services, Deployments, Jobs, NetworkPolicies)
./k8s/scripts/deploy-resources.sh
```

**Manual alternative using Kustomize:**

```bash
# Deploy everything with base configuration
kubectl apply -k k8s/base

# Or deploy with production overlay (recommended)
kubectl apply -k k8s/overlays/production

# Verify deployment
kubectl get all -n my-project-prod
```

**Manual alternative using kubectl directly:**

```bash
# Deploy in correct order
kubectl apply -f k8s/base/namespace.yaml
kubectl apply -f k8s/base/persistentvolumeclaims/
kubectl apply -f k8s/base/services/
kubectl apply -f k8s/base/deployments/
kubectl apply -f k8s/base/jobs/
kubectl apply -f k8s/base/networkpolicies/
```

**Note**: Manual kubectl requires careful ordering to avoid dependency issues.

### Step 7: Run Initialization Jobs

**Using the CLI:**

```bash
# The CLI automatically waits for and monitors initialization jobs
uv run api-forge-cli deploy up k8s
```

**Using the script:**

```bash
# The deploy-resources.sh script includes job deployment
# Jobs run automatically after resource deployment
./k8s/scripts/deploy-resources.sh

# Monitor job status
kubectl get jobs -n my-project-prod
```

**Manual alternative:**

```bash
# Wait for PostgreSQL to be ready
kubectl wait --for=condition=ready pod -l app=postgres -n my-project-prod --timeout=300s

# Run PostgreSQL verifier job
kubectl apply -f k8s/base/jobs/postgres-verifier.yaml

# Wait for job completion
kubectl wait --for=condition=complete job/postgres-verifier -n my-project-prod --timeout=300s

# Check job logs
kubectl logs -n my-project-prod job/postgres-verifier

# Run Temporal schema setup job
kubectl apply -f k8s/base/jobs/temporal-schema-setup.yaml

# Wait for job completion
kubectl wait --for=condition=complete job/temporal-schema-setup -n my-project-prod --timeout=300s
```

### Step 8: Verify Deployment

**Using the CLI:**

```bash
# Check overall status
uv run api-forge-cli deploy status k8s

# View application logs
kubectl logs -n api-forge-prod -l app=app --tail=100 -f
```

**Manual alternative:**

```bash
# Check all resources
kubectl get all -n my-project-prod

# Check pod status
kubectl get pods -n my-project-prod

# Check service endpoints
kubectl get endpoints -n my-project-prod

# Test health endpoint
kubectl port-forward -n my-project-prod svc/app 8000:8000
curl http://localhost:8000/health

# Access FastAPI docs
open http://localhost:8000/docs
```

## Configuration

### Environment-Specific Overlays

Use Kustomize overlays for environment-specific configuration:

**k8s/overlays/production/kustomization.yaml**:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: my-project-prod

bases:
  - ../../base

replicas:
  - name: app
    count: 3
  - name: worker
    count: 2

images:
  - name: my-project-app
    newTag: v1.0.0

configMapGenerator:
  - name: app-env
    behavior: merge
    literals:
      - APP_ENVIRONMENT=production
      - LOG_LEVEL=INFO

resources:
  - ingress.yaml
  - hpa.yaml
```

### ConfigMaps

ConfigMaps are created dynamically at deployment time from your project's configuration files, not from static manifest files. This ensures your Kubernetes deployment uses the same configuration as your local development environment.

**How ConfigMaps are created:**

The CLI (`api-forge-cli deploy up k8s`) or the `deploy-config.sh` script automatically creates ConfigMaps from:

1. **`config.yaml`** - Your main application configuration
2. **`.env`** - Environment variables
3. **PostgreSQL configs** - `postgresql.conf`, `pg_hba.conf`
4. **Redis configs** - `redis.conf`
5. **Other service configs** - As defined in your project

**Example: Creating ConfigMap from config.yaml**

```bash
# This is done automatically by the CLI or script
kubectl create configmap app-config \
  --from-file=config.yaml=config.yaml \
  -n my-project-prod

# View the created ConfigMap
kubectl get configmap app-config -n my-project-prod -o yaml
```

**Mounting ConfigMaps in deployments:**

Your deployment manifests mount these dynamically created ConfigMaps:

```yaml
volumeMounts:
  - name: config
    mountPath: /app/config.yaml
    subPath: config.yaml
  - name: env
    mountPath: /app/.env
    subPath: .env
volumes:
  - name: config
    configMap:
      name: app-config
  - name: env
    configMap:
      name: env-config
```

**Updating configuration:**

To update configuration after deployment:

```bash
# Update the ConfigMap
kubectl create configmap app-config \
  --from-file=config.yaml=config.yaml \
  -n my-project-prod \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart pods to pick up changes
kubectl rollout restart deployment/app -n my-project-prod
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

Set appropriate resource requests and limits:

```yaml
resources:
  requests:
    cpu: 250m
    memory: 256Mi
  limits:
    cpu: 1000m
    memory: 512Mi
```

**Guidelines**:
- **Requests**: Minimum resources guaranteed
- **Limits**: Maximum resources allowed
- **FastAPI App**: 250m CPU, 256-512Mi memory
- **Worker**: 250m CPU, 256-512Mi memory
- **PostgreSQL**: 500m CPU, 1Gi memory
- **Redis**: 100m CPU, 128Mi memory

### Horizontal Pod Autoscaling

Scale based on CPU/memory utilization:

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

Expose your FastAPI application via Ingress:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app-ingress
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - api.example.com
      secretName: app-tls
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: app
                port:
                  number: 8000
```

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

### GitHub Actions

```yaml
name: Deploy to Kubernetes

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Build Docker image
        run: |
          docker build -t ${{ secrets.REGISTRY }}/my-project-app:${{ github.sha }} .
          docker push ${{ secrets.REGISTRY }}/my-project-app:${{ github.sha }}
      
      - name: Configure kubectl
        uses: azure/k8s-set-context@v3
        with:
          kubeconfig: ${{ secrets.KUBECONFIG }}
      
      - name: Deploy to Kubernetes
        run: |
          cd k8s/overlays/production
          kustomize edit set image my-project-app=${{ secrets.REGISTRY }}/my-project-app:${{ github.sha }}
          kubectl apply -k .
      
      - name: Wait for deployment
        run: |
          kubectl rollout status deployment/app -n my-project-prod
```

### GitLab CI

```yaml
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl config set-cluster k8s --server="$K8S_SERVER"
    - kubectl config set-credentials gitlab --token="$K8S_TOKEN"
    - kubectl config set-context default --cluster=k8s --user=gitlab
    - kubectl config use-context default
    - kubectl apply -k k8s/overlays/production
    - kubectl rollout status deployment/app -n my-project-prod
  only:
    - main
```

## Best Practices

1. **Use namespaces** for environment isolation
2. **Set resource requests and limits** for all containers
3. **Implement health checks** (liveness and readiness)
4. **Use secrets** for sensitive data, never ConfigMaps
5. **Enable NetworkPolicies** to restrict traffic
6. **Use Ingress** with TLS for external access
7. **Implement HPA** for automatic scaling
8. **Use PersistentVolumes** for stateful data
9. **Tag images** with versions, not `latest`
10. **Monitor and log** everything

## Related Documentation

- [Docker Dev Environment](./fastapi-docker-dev-environment.md) - Local testing before deployment
- [Docker Compose Production](./fastapi-production-deployment-docker-compose.md) - Alternative deployment
- [Testing Strategy](./fastapi-testing-strategy.md) - Test before deploying

## Additional Resources

- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Kustomize Documentation](https://kustomize.io/)
- [Helm Documentation](https://helm.sh/docs/)
- [External Secrets Operator](https://external-secrets.io/)
- [cert-manager](https://cert-manager.io/)
