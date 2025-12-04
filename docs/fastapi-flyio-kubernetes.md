# FastAPI Fly.io Kubernetes (FKS) Deployment

This document covers deploying API Forge to Fly.io's Kubernetes Service (FKS), including compatibility analysis with our existing Helm-based deployment and future CLI design considerations.

## Overview

Fly.io Kubernetes Service (FKS) is Fly.io's managed Kubernetes offering that integrates with their global Anycast network. It provides a different deployment model than traditional Kubernetes clusters (GKE, EKS, AKS), with some unique advantages and constraints.

> **Status:** FKS support is planned but not yet implemented. This document captures research and design decisions for future development.

## FKS Key Characteristics

### How FKS Differs from Standard Kubernetes

| Aspect | Standard K8s (GKE, EKS, AKS) | Fly.io FKS |
|--------|------------------------------|------------|
| **Ingress** | Ingress resource + Ingress Controller (nginx) | Not used - Fly's Anycast proxy handles routing |
| **LoadBalancer** | Cloud provider provisions external IP | Maps directly to Fly.io's edge network |
| **TLS Certificates** | cert-manager + Let's Encrypt | Automatic - Fly provisions and renews certs |
| **DNS** | Manual - point domain to LB IP | Automatic `*.fly.dev` + custom domain support |
| **Global Distribution** | Multi-region requires complex setup | Built-in - deploy to 30+ regions easily |
| **Scaling** | HPA, node autoscaling | Fly Machines with automatic scaling |

### What FKS Provides Automatically

1. **Automatic TLS** - No cert-manager, no Let's Encrypt configuration needed
2. **Global Anycast** - Traffic routed to nearest region automatically
3. **DDoS Protection** - Built into Fly's edge network
4. **Automatic DNS** - `yourapp.fly.dev` domains provisioned automatically
5. **Custom Domains** - Simple CNAME setup with automatic certificate issuance

### What FKS Does NOT Use

- ❌ Ingress resources
- ❌ Ingress Controllers (nginx, traefik, etc.)
- ❌ cert-manager
- ❌ External DNS controllers
- ❌ Cloud provider load balancer integrations

## Exposing Services on FKS

### LoadBalancer Service (Recommended)

On FKS, you expose services using `type: LoadBalancer` which Fly.io intercepts:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: app
  annotations:
    # Fly-specific annotations
    fly.io/app: my-fastapi-app
spec:
  type: LoadBalancer
  ports:
    - port: 443
      targetPort: 8000
  selector:
    app.kubernetes.io/name: app
```

Fly.io then:
1. Creates a Fly App if it doesn't exist
2. Provisions `my-fastapi-app.fly.dev` domain
3. Issues TLS certificate automatically
4. Routes global traffic through Anycast

### Custom Domains

```yaml
metadata:
  annotations:
    fly.io/app: my-fastapi-app
    fly.io/domains: "api.example.com,api.mycompany.io"
```

Then add a CNAME record:
```
api.example.com CNAME my-fastapi-app.fly.dev
```

Fly automatically issues certificates for custom domains.

## Compatibility Analysis

### Current API Forge Features vs FKS

| API Forge Feature | Standard K8s | FKS Compatibility |
|-------------------|--------------|-------------------|
| Helm chart deployment | ✅ Works | ✅ Works (FKS is standard K8s) |
| PostgreSQL StatefulSet | ✅ Works | ⚠️ Consider Fly Postgres instead |
| Redis Deployment | ✅ Works | ⚠️ Consider Fly Redis (Upstash) |
| Temporal | ✅ Works | ✅ Works |
| `--ingress` flag | Creates Ingress | ❌ Should create LoadBalancer instead |
| `--ingress-host` | Sets Ingress host | Should set Fly app name |
| `--ingress-tls-secret` | References K8s Secret | ❌ Not needed |
| `--ingress-tls auto` | Uses cert-manager | ❌ Not needed |
| NetworkPolicies | ✅ Works | ✅ Works |
| PersistentVolumeClaims | ✅ Works | ✅ Works (Fly Volumes) |

### Components That Need Adaptation

1. **Ingress → LoadBalancer Service**
   - Replace Ingress resource with LoadBalancer Service
   - Add Fly-specific annotations
   - Remove Ingress Controller dependency

2. **TLS Configuration**
   - Remove cert-manager setup
   - Remove TLS secret references
   - Fly handles all certificate management

3. **Database Considerations**
   - Could use in-cluster PostgreSQL (works but not recommended)
   - Better: Use Fly Postgres (managed, with replicas)
   - Fly Postgres uses their own clustering solution

4. **Redis Considerations**
   - Could use in-cluster Redis (works)
   - Alternative: Upstash Redis (Fly partnership, serverless)

## Proposed CLI Design

### Option A: Unified Command with Detection (Complex)

```bash
# CLI detects cluster type and adapts
uv run api-forge-cli deploy up k8s --ingress --ingress-host myapp

# On FKS: Creates LoadBalancer Service with Fly annotations
# On standard K8s: Creates Ingress + optional cert-manager
```

**Pros:** Single command, automatic adaptation
**Cons:** Complex logic, harder to debug, surprises users

### Option B: Separate Target (Recommended)

```bash
# Explicit Fly.io target
uv run api-forge-cli deploy up fly --app myapp --region ord

# Standard Kubernetes
uv run api-forge-cli deploy up k8s --ingress --ingress-host api.example.com
```

**Pros:** Clear intent, simpler implementation, Fly-specific optimizations
**Cons:** Another target to maintain

### Recommended: Option B

Separate targets are better because:

1. **Fly has unique features** - Machines, regions, Fly Postgres are Fly-specific
2. **Simpler Helm chart** - No conditionals for "is this FKS?"
3. **Better UX** - Users explicitly choose their target
4. **Fly CLI integration** - Can leverage `flyctl` where appropriate
5. **Different defaults** - FKS might skip in-cluster Postgres entirely

### Proposed CLI Commands

```bash
# Setup Fly.io (one-time)
uv run api-forge-cli deploy setup fly
# - Verifies flyctl is installed
# - Authenticates with Fly.io
# - Creates Fly organization if needed

# Deploy to Fly Kubernetes
uv run api-forge-cli deploy up fly \
  --app my-fastapi-app \
  --region ord \
  --postgres fly           # Use Fly Postgres (recommended)
  --redis upstash          # Use Upstash Redis (optional)

# Or with in-cluster databases (not recommended for production)
uv run api-forge-cli deploy up fly \
  --app my-fastapi-app \
  --postgres in-cluster \
  --redis in-cluster

# Status
uv run api-forge-cli deploy status fly --app my-fastapi-app

# Teardown
uv run api-forge-cli deploy down fly --app my-fastapi-app
```

### Implementation Phases

**Phase 1: Basic FKS Support**
- Deploy app and worker to FKS
- Use LoadBalancer Service for external access
- In-cluster PostgreSQL and Redis (same as standard K8s)

**Phase 2: Fly-Native Services**
- Fly Postgres integration
- Upstash Redis integration
- Fly Volumes for persistent storage

**Phase 3: Advanced Features**
- Multi-region deployment
- Fly Machines autoscaling
- Fly.io metrics integration

## Helm Chart Modifications for FKS

### Conditional Ingress vs LoadBalancer

```yaml
# values.yaml
app:
  # Standard K8s ingress (existing)
  ingress:
    enabled: false
    # ... existing config
  
  # Fly.io specific (new)
  fly:
    enabled: false
    app: ""
    regions: ["ord"]
    domains: []
```

### FKS-Specific Service Template

```yaml
# templates/services/app-fly.yaml
{{- if .Values.app.fly.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: {{ .Values.app.name | default "app" }}
  namespace: {{ .Values.global.namespace }}
  annotations:
    fly.io/app: {{ .Values.app.fly.app | required "app.fly.app is required" }}
    {{- if .Values.app.fly.domains }}
    fly.io/domains: {{ .Values.app.fly.domains | join "," | quote }}
    {{- end }}
  labels:
    {{- include "api-forge.labels" . | nindent 4 }}
spec:
  type: LoadBalancer
  ports:
    - port: 443
      targetPort: {{ .Values.app.service.port | default 8000 }}
      name: https
  selector:
    app.kubernetes.io/name: {{ .Values.app.name | default "app" }}
{{- end }}
```

## TLS Strategy by Platform

| Platform | TLS Strategy | CLI Flag |
|----------|--------------|----------|
| **Minikube** | None (HTTP) or self-signed | `--ingress` (no TLS) |
| **Standard K8s** | cert-manager + Let's Encrypt | `--ingress --ingress-tls auto` |
| **Standard K8s** | Manual certificate | `--ingress --ingress-tls-secret name` |
| **AWS EKS** | ACM certificate | `--ingress` + ACM annotation |
| **GKE** | Google-managed cert | `--ingress` + ManagedCertificate |
| **Fly.io FKS** | Automatic (Fly-managed) | `deploy up fly` (TLS automatic) |

## Database Strategy by Platform

| Platform | Recommended PostgreSQL | Recommended Redis |
|----------|----------------------|-------------------|
| **Development** | Docker Compose (local) | Docker Compose (local) |
| **Minikube** | In-cluster StatefulSet | In-cluster Deployment |
| **Standard K8s** | In-cluster or managed (RDS, Cloud SQL) | In-cluster or managed |
| **Fly.io FKS** | Fly Postgres (managed) | Upstash Redis or in-cluster |

## Migration Path

### From Docker Compose to FKS

1. **Test locally** with `deploy up dev`
2. **Test on Minikube** with `deploy up k8s`
3. **Deploy to FKS** with `deploy up fly`

### From Standard K8s to FKS

1. **Export data** from existing PostgreSQL
2. **Create Fly Postgres** cluster
3. **Import data** to Fly Postgres
4. **Deploy app** to FKS with `--postgres fly`
5. **Update DNS** to point to Fly

## Current Limitations

1. **FKS is relatively new** - Some features may change
2. **Fly Postgres clustering** - Different from standard PostgreSQL HA
3. **Temporal on Fly** - May need special consideration for workflows
4. **Cost model** - Fly charges differently than traditional cloud

## Related Documentation

- [Kubernetes Deployment Guide](./fastapi-kubernetes-deployment.md) - Standard K8s deployment
- [Ingress Configuration](./fastapi-kubernetes-ingress.md) - Ingress and TLS for standard K8s
- [Docker Dev Environment](./fastapi-docker-dev-environment.md) - Local development

## External Resources

- [Fly.io Kubernetes Documentation](https://fly.io/docs/kubernetes/)
- [Fly.io FKS Quickstart](https://fly.io/docs/kubernetes/fks-quickstart/)
- [Fly Postgres](https://fly.io/docs/postgres/)
- [Upstash Redis on Fly](https://fly.io/docs/reference/redis/)
