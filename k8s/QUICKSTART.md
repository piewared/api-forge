# Kubernetes Deployment - Quick Reference

## 🚀 One-Command Deployment

```bash
# Complete deployment in 4 commands
./k8s/scripts/build-images.sh && \
cd infra/secrets && ./generate_secrets.sh && cd ../.. && \
./k8s/scripts/apply-secrets.sh && \
./k8s/scripts/deploy-resources.sh
```

> ℹ️ Before running `apply-secrets.sh`, copy `infra/secrets/user-provided.env.example` to `infra/secrets/user-provided.env` and fill in the deterministic secrets (OIDC client secrets, etc.).

---

## 📋 Deployment Checklist

- [ ] **Step 1**: Build Docker images
  ```bash
  ./k8s/scripts/build-images.sh
  ```
  ✅ Builds: postgres, redis, temporal, app images

- [ ] **Step 2**: Generate secrets
  ```bash
  cd infra/secrets && ./generate_secrets.sh && cd ../..
  ```
  ✅ Creates: TLS certs, passwords, signing secrets

- [ ] **Step 3**: Apply Kubernetes secrets (after filling `infra/secrets/user-provided.env`)
  ```bash
  ./k8s/scripts/apply-secrets.sh
  ```
  ✅ Uploads: 5 secret resources to cluster (passwords, TLS certs, OIDC client secrets)

- [ ] **Step 4**: Deploy resources
  ```bash
  ./k8s/scripts/deploy-resources.sh
  ```
  ✅ Deploys: All pods, services, configs in order

---

## 🎯 What Gets Deployed

### Infrastructure Layer
- ✅ Namespace: `api-forge-prod`
- ✅ Storage: 5 PersistentVolumeClaims
- ✅ ConfigMaps: 5 configuration files
- ✅ Services: 5 ClusterIP services

### Data Layer
- ✅ PostgreSQL 15 (with TLS)
- ✅ Redis 7 (with password)

### Application Layer
- ✅ Temporal Server (workflow engine)
- ✅ Temporal Web UI
- ✅ Temporal Admin Tools
- ✅ FastAPI Application
- ✅ Temporal Worker (background tasks)

### Initialization Jobs
- ✅ PostgreSQL verifier (security checks)
- ✅ Temporal schema setup
- ✅ Temporal namespace initialization

---

## 🔍 Verification Commands

```bash
# Check all pods
kubectl get pods -n api-forge-prod

# Check services
kubectl get svc -n api-forge-prod

# Check app health
kubectl logs -n api-forge-prod -l app.kubernetes.io/name=app | grep healthy

# Expected output:
# ✓ Database is healthy
# ✓ Redis is healthy
# ✓ Temporal is healthy
```

---

## 🌐 Access Services

### Application API
```bash
kubectl port-forward -n api-forge-prod svc/app 8000:8000
curl http://localhost:8000/health
```

### Temporal Web UI
```bash
kubectl port-forward -n api-forge-prod svc/temporal-web 8080:8080
open http://localhost:8080
```

### PostgreSQL (for debugging)
```bash
kubectl port-forward -n api-forge-prod svc/postgres 5432:5432
psql postgresql://appuser:PASSWORD@localhost:5432/appdb
```

### Redis (for debugging)
```bash
kubectl port-forward -n api-forge-prod svc/redis 6379:6379
redis-cli -h localhost -p 6379 -a PASSWORD ping
```

---

## 🧹 Cleanup

### Remove everything
```bash
kubectl delete namespace api-forge-prod
```

### Remove images (Minikube)
```bash
minikube ssh "docker images | grep 'api-forge\|my-temporal' | awk '{print \$3}' | xargs docker rmi -f"
```

---

## 🐛 Common Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| `ImagePullBackOff` | Images not in cluster | Run `./build-images.sh` |
| Secrets not found | Missing secrets | Run `./apply-secrets.sh` |
| Connection refused | Service selector mismatch | Don't use `kubectl apply -k` |
| Temporal won't start | Schemas not initialized | Schema job runs automatically |
| Pod crashes immediately | Config/secret error | Check logs: `kubectl logs` |

---

## 📚 Documentation

- **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** - Complete step-by-step guide
- **[scripts/README.md](scripts/README.md)** - Script documentation
- **[BUILD_CONTEXTS.md](BUILD_CONTEXTS.md)** - Docker build context info
- **[LOCAL_TESTING.md](LOCAL_TESTING.md)** - Local testing guide

---

## ⚠️ Important Notes

1. **You CAN use `kubectl apply -k k8s/base/` now**
   - The problematic `commonLabels` has been disabled
   - However, the deployment script is recommended as it handles dependencies and health checks
   - With `kubectl apply -k`, some pods may restart until dependencies are ready

2. **Deployment order matters**
   - Database → Temporal schemas → Temporal → App/Worker
   - Scripts handle this automatically

3. **Environment variables**
   - App uses `config.yaml` with `${VAR:-default}` patterns
   - ConfigMap `app-env` (generated from `.env`) provides the variables
   - Deployments use `envFrom` to load all env vars at once
   - Operational values (TZ, LOG_FORMAT, LOG_LEVEL) are hardcoded in manifests

4. **Secrets**
   - Generate with `infra/secrets/generate_secrets.sh`
   - Located in `infra/secrets/keys/` and `infra/secrets/certs/`
   - Never commit to version control

---

## 🎓 Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                  Application                    │
│              (FastAPI + Uvicorn)                │
└───────┬─────────────────┬──────────────┬────────┘
        │                 │              │
        ▼                 ▼              ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  PostgreSQL  │  │    Redis     │  │   Temporal   │
│   (Data)     │  │  (Cache)     │  │ (Workflows)  │
└──────────────┘  └──────────────┘  └──────────────┘
```

**Data Flow**:
1. Client → App (HTTP requests)
2. App → PostgreSQL (persistent data)
3. App → Redis (sessions, cache, rate limiting)
4. App → Temporal (async workflows)

**Security**:
- All secrets in Kubernetes Secrets
- TLS for PostgreSQL
- Password-protected Redis
- CSRF protection
- Session fingerprinting

---

## 📊 Resource Requirements

| Component | CPU Request | Memory Request | Storage |
|-----------|-------------|----------------|---------|
| PostgreSQL | 500m | 512Mi | 10Gi |
| Redis | 100m | 128Mi | 5Gi |
| Temporal | 500m | 512Mi | - |
| App | 250m | 128Mi | 5Gi (logs) |
| **Total** | **~1.5 CPU** | **~1.5Gi RAM** | **~20Gi** |

**Recommended Minikube config**:
```bash
minikube start --cpus=4 --memory=8192 --disk-size=40g
```

---

## 🔄 Update Workflow

### Update Application Code
```bash
# 1. Rebuild app image
./k8s/scripts/build-images.sh

# 2. Restart app
kubectl rollout restart deployment/app -n api-forge-prod
```

### Update Configuration
```bash
# 1. Edit .env or config.yaml
vim .env
# or
vim config.yaml

# 2. Sync changes and deploy
./k8s/scripts/deploy-config.sh --restart

# This automatically:
# - Copies files to k8s/base/.k8s-sources/
# - Generates ConfigMaps via Kustomize
# - Restarts affected deployments
```

### Update Secrets
```bash
# 1. Regenerate secrets
cd infra/secrets && ./generate_secrets.sh && cd ../..

# 2. Update Kubernetes secrets
./k8s/scripts/apply-secrets.sh

# 3. Restart affected pods
kubectl rollout restart deployment/postgres -n api-forge-prod
kubectl rollout restart deployment/redis -n api-forge-prod
kubectl rollout restart deployment/app -n api-forge-prod
```
