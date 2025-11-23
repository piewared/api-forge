# Local Kubernetes Testing Guide

## Overview

Testing Kubernetes configurations locally before deploying to production is a critical best practice. This guide covers the most popular local Kubernetes solutions.

---

## 🎯 Quick Comparison

| Tool | Best For | Resource Usage | Setup Time | Production Similarity |
|------|----------|----------------|------------|----------------------|
| **Minikube** | General testing | Medium | 5 min | High |
| **kind** | CI/CD, quick tests | Low | 2 min | High |
| **k3s/k3d** | Lightweight testing | Very Low | 3 min | Medium |
| **Docker Desktop** | Mac/Windows users | Medium | 1 min | Medium |
| **MicroK8s** | Ubuntu/Linux | Low | 3 min | High |

---

## Option 1: Minikube (Recommended for This Project) ⭐

**Best choice for testing production-like configs with multi-container setups**

### Why Minikube?
- ✅ Most mature and feature-complete
- ✅ Supports LoadBalancer, Ingress, persistent volumes
- ✅ Easy to use
- ✅ Good documentation
- ✅ Works on Linux, Mac, Windows

### Installation

```bash
# Linux
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube

# Mac (Homebrew)
brew install minikube

# Windows (Chocolatey)
choco install minikube
```

### Start Minikube

```bash
# Start with sufficient resources for your stack
minikube start \
  --cpus=4 \
  --memory=8192 \
  --disk-size=50g \
  --driver=docker

# Enable useful addons
minikube addons enable metrics-server
minikube addons enable dashboard
```

### Deploy Your Configs

```bash
# 1. Build Docker images and load into Minikube
# Note: Minikube has its own Docker daemon
eval $(minikube docker-env)

# Build images (automated script handles Minikube context)
./k8s/scripts/build-images.sh

# Verify images are in Minikube
minikube image ls | grep -E "app_data|temporal|api-forge"

# 2. Generate and create secrets
cd infra/secrets && ./generate_secrets.sh && cd ../..
./k8s/scripts/apply-secrets.sh

# 3. Deploy your configs
kubectl apply -k k8s/base/

# 4. Watch deployment
kubectl get pods -n api-forge-prod -w

# 5. Check service status
kubectl get all -n api-forge-prod
```

### Access Services

```bash
# Get service URLs
minikube service app -n api-forge-prod --url
minikube service temporal-web -n api-forge-prod --url

# Or use port forwarding
kubectl port-forward -n api-forge-prod svc/app 8000:8000
kubectl port-forward -n api-forge-prod svc/temporal-web 8080:8080
kubectl port-forward -n api-forge-prod svc/postgres 5432:5432

# Access Kubernetes dashboard
minikube dashboard
```

### Useful Minikube Commands

```bash
# Check cluster status
minikube status

# SSH into the node
minikube ssh

# View logs
minikube logs

# Stop (preserves state)
minikube stop

# Delete cluster
minikube delete

# Reset Docker environment
eval $(minikube docker-env --unset)
```

---

## Option 2: kind (Kubernetes in Docker) 🐳

**Best for quick testing and CI/CD pipelines**

### Why kind?
- ✅ Very fast startup
- ✅ Low resource usage
- ✅ Easy multi-node clusters
- ✅ Great for CI/CD
- ✅ Official Kubernetes SIG project

### Installation

```bash
# Linux
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# Mac (Homebrew)
brew install kind

# Windows (Chocolatey)
choco install kind
```

### Create Cluster with Custom Config

```bash
# Create kind config with extra port mappings
cat <<EOF > kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  extraPortMappings:
  - containerPort: 8000
    hostPort: 8000
    protocol: TCP
  - containerPort: 8080
    hostPort: 8080
    protocol: TCP
  - containerPort: 5432
    hostPort: 5432
    protocol: TCP
EOF

# Create cluster
kind create cluster --name api-forge --config kind-config.yaml

# Verify
kubectl cluster-info --context kind-api-forge
```

### Load Images into kind

```bash
# Build images and load into kind (automated script)
./k8s/scripts/build-images.sh
```

### Deploy

```bash
# Create secrets
./k8s/scripts/apply-secrets.sh

# Deploy
kubectl apply -k k8s/base/

# Check status
kubectl get all -n api-forge-prod
```

### Cleanup

```bash
# Delete cluster
kind delete cluster --name api-forge
```

---

## Option 3: k3d (k3s in Docker) 🚀

**Best for resource-constrained environments**

### Why k3d?
- ✅ Extremely lightweight
- ✅ Very fast
- ✅ Built-in load balancer
- ✅ Easy multi-cluster setup

### Installation

```bash
# Linux/Mac
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash

# Mac (Homebrew)
brew install k3d

# Windows (Chocolatey)
choco install k3d
```

### Create Cluster

```bash
# Create cluster with port mappings
k3d cluster create api-forge \
  --port 8000:8000@loadbalancer \
  --port 8080:8080@loadbalancer \
  --port 5432:5432@loadbalancer \
  --agents 2

# Build and load images (automated script)
./k8s/scripts/build-images.sh
```

### Deploy and Test

```bash
./k8s/scripts/apply-secrets.sh
kubectl apply -k k8s/base/
kubectl get all -n api-forge-prod
```

### Cleanup

```bash
k3d cluster delete api-forge
```

---

## Option 4: Docker Desktop Kubernetes 🐋

**Best for Mac/Windows users who already have Docker Desktop**

### Why Docker Desktop?
- ✅ Already installed with Docker Desktop
- ✅ One-click enable
- ✅ Integrates with Docker commands
- ✅ Good for beginners

### Enable Kubernetes

1. Open Docker Desktop
2. Go to Settings → Kubernetes
3. Check "Enable Kubernetes"
4. Click "Apply & Restart"
5. Wait for green indicator

### Deploy

```bash
# Build images (automated script)
./k8s/scripts/build-images.sh

# Deploy
./k8s/scripts/apply-secrets.sh
kubectl apply -k k8s/base/
kubectl get all -n api-forge-prod

# Access services via localhost
kubectl port-forward -n api-forge-prod svc/app 8000:8000
```

---

## 🧪 Testing Workflow

### 1. Pre-Deployment Validation

```bash
# Validate Kubernetes YAML syntax
kubectl apply -k k8s/base/ --dry-run=client

# Validate with server-side checks (requires cluster)
kubectl apply -k k8s/base/ --dry-run=server

# View generated manifests
kubectl kustomize k8s/base/

# Check for security issues (optional, requires kubesec)
kubesec scan k8s/base/deployments/*.yaml
```

### 2. Deploy and Monitor

```bash
# Deploy
kubectl apply -k k8s/base/

# Watch pod startup
kubectl get pods -n api-forge-prod -w

# Check events
kubectl get events -n api-forge-prod --sort-by='.lastTimestamp'

# View logs from all pods
kubectl logs -n api-forge-prod -l app=postgres --tail=50
kubectl logs -n api-forge-prod -l app=redis --tail=50
kubectl logs -n api-forge-prod -l app=temporal --tail=50
kubectl logs -n api-forge-prod -l app=app --tail=50
```

### 3. Test Services

```bash
# Check if pods are ready
kubectl get pods -n api-forge-prod

# Test database connection
kubectl exec -n api-forge-prod -it deploy/postgres -- \
  psql -U app_owner -d appdb -c "SELECT version();"

# Test Redis connection
kubectl exec -n api-forge-prod -it deploy/redis -- \
  redis-cli -a $(kubectl get secret redis-secrets -n api-forge-prod -o jsonpath='{.data.password}' | base64 -d) ping

# Test application health endpoint
kubectl exec -n api-forge-prod -it deploy/app -- \
  curl -s http://localhost:8000/health

# Or port-forward and test from host
kubectl port-forward -n api-forge-prod svc/app 8000:8000 &
curl http://localhost:8000/health
curl http://localhost:8000/docs  # FastAPI OpenAPI docs
```

### 4. Test Init Jobs

```bash
# Check job status
kubectl get jobs -n api-forge-prod

# View job logs
kubectl logs -n api-forge-prod job/postgres-verifier
kubectl logs -n api-forge-prod job/temporal-schema-setup
kubectl logs -n api-forge-prod job/temporal-namespace-init

# Rerun a job (delete and reapply)
kubectl delete job postgres-verifier -n api-forge-prod
kubectl apply -f k8s/base/jobs/postgres-verifier.yaml
```

### 5. Test Storage

```bash
# Check PVC status
kubectl get pvc -n api-forge-prod

# Check if volumes are bound
kubectl describe pvc -n api-forge-prod

# Write test data to PostgreSQL
kubectl exec -n api-forge-prod -it deploy/postgres -- \
  psql -U app_owner -d appdb -c "CREATE TABLE test (id serial, data text);"

# Restart pod and verify data persists
kubectl rollout restart deployment/postgres -n api-forge-prod
kubectl exec -n api-forge-prod -it deploy/postgres -- \
  psql -U app_owner -d appdb -c "SELECT * FROM test;"
```

### 6. Test ConfigMaps and Secrets

```bash
# View ConfigMap contents
kubectl get configmap -n api-forge-prod
kubectl describe configmap postgres-config -n api-forge-prod

# Verify secrets exist (not their contents!)
kubectl get secrets -n api-forge-prod

# Check if secrets are mounted correctly
kubectl exec -n api-forge-prod -it deploy/postgres -- ls -la /run/secrets/
kubectl exec -n api-forge-prod -it deploy/app -- ls -la /run/secrets/
```

### 7. Test Security Contexts

```bash
# Verify pods are running as non-root
kubectl exec -n api-forge-prod -it deploy/postgres -- id
kubectl exec -n api-forge-prod -it deploy/redis -- id
kubectl exec -n api-forge-prod -it deploy/app -- id

# Check capabilities
kubectl exec -n api-forge-prod -it deploy/app -- \
  sh -c "cat /proc/1/status | grep Cap"
```

### 8. Test Health Probes

```bash
# Simulate pod failure and watch restart
kubectl exec -n api-forge-prod -it deploy/app -- kill 1

# Watch pod restart
kubectl get pods -n api-forge-prod -w

# Check probe endpoints manually
kubectl exec -n api-forge-prod -it deploy/postgres -- pg_isready
kubectl exec -n api-forge-prod -it deploy/redis -- redis-cli ping
```

---

## 🐛 Troubleshooting Local Clusters

### Common Issues

#### 1. Pods Stuck in Pending

```bash
# Check why
kubectl describe pod <pod-name> -n api-forge-prod

# Common causes:
# - Insufficient resources
# - PVC not bound
# - Image pull errors
```

#### 2. Image Pull Errors (ImagePullBackOff)

```bash
# For Minikube - ensure you're using Minikube's Docker daemon
eval $(minikube docker-env)
docker images  # Should show your images

# For kind - ensure images are loaded
kind load docker-image <image-name> --name api-forge

# For k3d
k3d image import <image-name> -c api-forge

# Or use the automated build script which handles this:
./k8s/scripts/build-images.sh

# Check imagePullPolicy
# For local images, ensure it's set to: imagePullPolicy: IfNotPresent
```

#### 3. PVC Not Binding

```bash
# Check storage class
kubectl get storageclass

# Check PVC status
kubectl describe pvc <pvc-name> -n api-forge-prod

# For Minikube, ensure default storage class exists
minikube addons enable default-storageclass
minikube addons enable storage-provisioner
```

#### 4. Service Not Accessible

```bash
# Check service
kubectl get svc -n api-forge-prod

# Check endpoints (should list pod IPs)
kubectl get endpoints -n api-forge-prod

# Use port-forward as fallback
kubectl port-forward -n api-forge-prod svc/app 8000:8000
```

#### 5. Secrets Not Found

```bash
# Verify secrets exist
kubectl get secrets -n api-forge-prod

# Recreate if needed
./k8s/scripts/apply-secrets.sh

# Check secret keys
kubectl describe secret postgres-secrets -n api-forge-prod
```

---

## 📊 Recommended Setup for This Project

Based on your stack (PostgreSQL, Redis, Temporal, FastAPI), here's the **recommended approach**:

### For Linux Users: **Minikube**

```bash
# Install
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube

# Start with appropriate resources
minikube start --cpus=4 --memory=8192 --disk-size=50g

# Build images (automated script handles correct contexts)
./k8s/scripts/build-images.sh

./k8s/scripts/apply-secrets.sh
kubectl apply -k k8s/base/
kubectl get pods -n api-forge-prod -w
```

### For CI/CD or Quick Tests: **kind**

```bash
# Install
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind

# Create and test
kind create cluster --name api-forge
kind load docker-image app_data_postgres_image:latest --name api-forge
# ... load other images
kubectl apply -k k8s/base/
```

---

## 🎯 Next Steps

1. **Choose a local K8s solution** based on your OS and needs
2. **Install and start the cluster**
3. **Build your Docker images** within the cluster context
4. **Generate secrets** using `infra/secrets/generate_secrets.sh`
5. **Create K8s secrets** using `./k8s/scripts/apply-secrets.sh`
6. **Deploy configs** with `kubectl apply -k k8s/base/`
7. **Test thoroughly** using the testing workflow above
8. **Iterate** - make changes, redeploy, test again

---

## 📚 Additional Resources

- [Minikube Documentation](https://minikube.sigs.k8s.io/docs/)
- [kind Documentation](https://kind.sigs.k8s.io/)
- [k3d Documentation](https://k3d.io/)
- [Docker Desktop Kubernetes](https://docs.docker.com/desktop/kubernetes/)
- [kubectl Cheat Sheet](https://kubernetes.io/docs/reference/kubectl/cheatsheet/)

---

**Pro Tip**: Start with Minikube for the most production-like experience, then switch to kind for faster iteration once you're comfortable with the setup.
