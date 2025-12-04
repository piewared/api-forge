# FastAPI Kubernetes Ingress Configuration

Learn how to expose your FastAPI application externally using Kubernetes Ingress with API Forge. This guide covers Ingress setup, CLI usage, TLS configuration, and cloud provider integrations.

## Overview

API Forge includes built-in Ingress support for exposing your FastAPI application to external traffic. The Ingress resource provides:

- **Host-based routing** - Route traffic to your app based on hostname
- **TLS/HTTPS termination** - Secure connections with SSL certificates
- **Path-based routing** - Route different paths to different services
- **Load balancing** - Distribute traffic across pod replicas
- **Cloud provider integration** - Works with AWS ALB, GCP GCLB, Azure, and NGINX

> **Note:** Ingress is for the **app service only**. Internal services (PostgreSQL, Redis, Temporal) remain as ClusterIP services and are not exposed externally.

## Quick Start

Enable Ingress with the CLI:

```bash
# Enable ingress with default host (api.local)
uv run api-forge-cli deploy up k8s --ingress

# Custom hostname
uv run api-forge-cli deploy up k8s --ingress --ingress-host api.example.com

# With TLS (reference to a K8s TLS secret)
uv run api-forge-cli deploy up k8s --ingress --ingress-host api.example.com --ingress-tls-secret api-tls
```

## Prerequisites

Before enabling Ingress, ensure you have:

### 1. Ingress Controller Installed

An Ingress Controller must be installed in your cluster. The Ingress resource is just configuration - the controller does the actual routing.

**Minikube (local development):**
```bash
minikube addons enable ingress

# Verify the controller is running
kubectl get pods -n ingress-nginx
```

**Production clusters (GKE, EKS, AKS):**
```bash
# Install NGINX Ingress Controller via Helm
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace

# Wait for the controller to be ready
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s

# Verify installation
kubectl get svc -n ingress-nginx
```

### 2. DNS Configuration (Production)

For production deployments, configure DNS to point to your cluster:

- **Minikube:** Add to `/etc/hosts`: `$(minikube ip) api.local`
- **Cloud providers:** Create a DNS A/CNAME record pointing to the Load Balancer IP

## CLI Reference

The `deploy up k8s` command supports three Ingress-related flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--ingress` | `false` | Enable Ingress for external access |
| `--ingress-host` | `api.local` | Hostname for the Ingress rule |
| `--ingress-tls-secret` | None | Kubernetes TLS secret name for HTTPS |

### Examples

**Basic Ingress (HTTP only):**
```bash
uv run api-forge-cli deploy up k8s --ingress
# Access at: http://api.local (requires /etc/hosts entry)
```

**Custom hostname:**
```bash
uv run api-forge-cli deploy up k8s --ingress --ingress-host myapi.example.com
# Access at: http://myapi.example.com
```

**HTTPS with existing TLS secret:**
```bash
uv run api-forge-cli deploy up k8s \
  --ingress \
  --ingress-host api.example.com \
  --ingress-tls-secret api-tls
# Access at: https://api.example.com
```

## How Ingress Routing Works

Understanding the request flow helps troubleshoot issues:

```
Internet Request (https://api.example.com/docs)
    │
    ▼
DNS Lookup
    │ api.example.com → 34.123.45.67 (Load Balancer IP)
    ▼
Cloud Load Balancer
    │ Provisioned by Ingress Controller
    ▼
Ingress Controller Pods (nginx)
    │ 1. Reads HTTP Host header from request
    │ 2. Matches against Ingress rules
    │ 3. Finds: host=api.example.com → service=app:8000
    ▼
Kubernetes Service (app)
    │ ClusterIP, port 8000
    ▼
FastAPI Pod(s)
    │ Your application
    ▼
Response flows back through the chain
```

**Key Points:**

1. The browser automatically sets the `Host` header from the URL
2. NGINX Ingress matches this header against configured Ingress resources
3. Traffic is proxied to the backend Kubernetes Service
4. The Service load-balances across pod replicas

## Configuration

### Values.yaml Structure

The Ingress configuration lives in `infra/helm/api-forge/values.yaml`:

```yaml
app:
  ingress:
    enabled: false              # Set to true or use --ingress flag
    className: nginx            # Ingress controller class
    annotations: {}             # Provider-specific annotations
    hosts:
      - host: api-forge.local
        paths:
          - path: /
            pathType: Prefix
    tls: []                     # TLS configuration
```

When using CLI flags, they override these values:

```bash
# CLI command:
uv run api-forge-cli deploy up k8s --ingress --ingress-host api.example.com --ingress-tls-secret api-tls

# Equivalent values.yaml:
app:
  ingress:
    enabled: true
    hosts:
      - host: api.example.com
        paths:
          - path: /
            pathType: Prefix
    tls:
      - secretName: api-tls
        hosts:
          - api.example.com
```

### Direct values.yaml Configuration

For more complex setups, edit `values.yaml` directly:

```yaml
app:
  ingress:
    enabled: true
    className: nginx
    annotations:
      nginx.ingress.kubernetes.io/ssl-redirect: "true"
      nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    hosts:
      - host: api.example.com
        paths:
          - path: /
            pathType: Prefix
          - path: /api/v2
            pathType: Prefix
    tls:
      - secretName: api-tls
        hosts:
          - api.example.com
```

## TLS/HTTPS Configuration

### Option 1: Manual TLS Secret

Create a TLS secret from existing certificates:

```bash
# Create TLS secret from certificate files
kubectl create secret tls api-tls \
  --cert=path/to/tls.crt \
  --key=path/to/tls.key \
  -n api-forge-prod

# Deploy with TLS
uv run api-forge-cli deploy up k8s \
  --ingress \
  --ingress-host api.example.com \
  --ingress-tls-secret api-tls
```

### Option 2: Cert-Manager (Recommended for Production)

Use [cert-manager](https://cert-manager.io/) for automatic Let's Encrypt certificates:

**1. Install cert-manager:**
```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update

helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true
```

**2. Create a ClusterIssuer:**
```yaml
# cluster-issuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    email: your-email@example.com
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
      - http01:
          ingress:
            class: nginx
```

```bash
kubectl apply -f cluster-issuer.yaml
```

**3. Configure Ingress in values.yaml:**
```yaml
app:
  ingress:
    enabled: true
    className: nginx
    annotations:
      cert-manager.io/cluster-issuer: letsencrypt-prod  # Triggers cert-manager
    hosts:
      - host: api.example.com
        paths:
          - path: /
            pathType: Prefix
    tls:
      - secretName: api-tls          # cert-manager creates this automatically
        hosts:
          - api.example.com
```

**How it works:**
1. Deploy the Ingress with the annotation and non-existent TLS secret
2. Cert-manager detects the `cert-manager.io/cluster-issuer` annotation
3. Cert-manager contacts Let's Encrypt, proves domain ownership via HTTP-01 challenge
4. Cert-manager creates the `api-tls` secret with the certificate
5. NGINX Ingress loads the certificate and serves HTTPS
6. Cert-manager auto-renews before expiry

## Cloud Provider Examples

### AWS ALB Ingress

Use AWS Application Load Balancer:

```yaml
app:
  ingress:
    enabled: true
    className: alb
    annotations:
      alb.ingress.kubernetes.io/scheme: internet-facing
      alb.ingress.kubernetes.io/target-type: ip
      alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:us-east-1:123456789:certificate/abc-123
      alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
      alb.ingress.kubernetes.io/ssl-redirect: '443'
    hosts:
      - host: api.example.com
        paths:
          - path: /
            pathType: Prefix
    tls:
      - hosts:
          - api.example.com
```

**Prerequisites:**
- AWS Load Balancer Controller installed
- ACM certificate created for your domain

### GKE with Google Cloud Load Balancer

```yaml
app:
  ingress:
    enabled: true
    className: gce
    annotations:
      kubernetes.io/ingress.global-static-ip-name: api-ip
      networking.gke.io/managed-certificates: api-cert
    hosts:
      - host: api.example.com
        paths:
          - path: /
            pathType: Prefix
```

**Prerequisites:**
- Reserve a global static IP: `gcloud compute addresses create api-ip --global`
- Create a ManagedCertificate resource

### Azure Application Gateway

```yaml
app:
  ingress:
    enabled: true
    className: azure/application-gateway
    annotations:
      appgw.ingress.kubernetes.io/ssl-redirect: "true"
      appgw.ingress.kubernetes.io/use-private-ip: "false"
    hosts:
      - host: api.example.com
        paths:
          - path: /
            pathType: Prefix
    tls:
      - secretName: api-tls
        hosts:
          - api.example.com
```

## Minikube Local Development

### Setup

```bash
# Enable ingress addon
minikube addons enable ingress

# Get Minikube IP
minikube ip
# Example output: 192.168.49.2

# Add to /etc/hosts
echo "$(minikube ip) api.local" | sudo tee -a /etc/hosts
```

### Deploy and Access

```bash
# Deploy with Ingress
uv run api-forge-cli deploy up k8s --ingress

# Access your API
curl http://api.local/health
open http://api.local/docs
```

### Minikube Tunnel (Alternative)

If you have DNS issues, use `minikube tunnel`:

```bash
# In a separate terminal (requires sudo)
minikube tunnel

# This exposes LoadBalancer services on localhost
# Access at http://localhost:8000 (if using LoadBalancer type)
```

## Why Use a Real Domain for Production

For production deployments, use your actual domain (not `api.local`) because:

| Feature | Why Real Domain Required |
|---------|-------------------------|
| **TLS/HTTPS** | Certificates are issued for specific domains. Mismatch causes TLS handshake failure. |
| **OAuth/OIDC** | Redirect URIs registered with providers (Google, Microsoft) must match exactly. |
| **Cookies** | Set with `domain=example.com`. Won't work if Host header differs. |
| **CORS** | Configured for specific origins. Mismatched Host breaks cross-origin requests. |
| **Browser Security** | Browsers set Host header automatically from URL - cannot be overridden. |

**For local development:** `api.local` works because you control the hosts file and don't need real TLS/OAuth.

## Service Types Comparison

Understanding when to use Ingress vs other service types:

| Type | Use Case | External Access | Example Services |
|------|----------|----------------|------------------|
| **ClusterIP** | Internal services only | No | PostgreSQL, Redis, Temporal |
| **NodePort** | Dev/testing, direct node access | Yes (nodeIP:port) | Debugging only |
| **LoadBalancer** | Single service exposure | Yes (external IP) | Simple apps without Ingress |
| **Ingress** | Production APIs, TLS, routing | Yes (hostname) | FastAPI app |

**Recommendation:** Use Ingress for the app service. Keep PostgreSQL, Redis, and Temporal as ClusterIP (internal only) for security.

## Troubleshooting

### Ingress Not Accessible

**1. Check Ingress Controller is running:**
```bash
kubectl get pods -n ingress-nginx
# Should show controller pods in Running state
```

**2. Check Ingress resource exists:**
```bash
kubectl get ingress -n api-forge-prod
kubectl describe ingress app -n api-forge-prod
```

**3. Check Ingress has an address:**
```bash
kubectl get ingress -n api-forge-prod -o wide
# ADDRESS column should show an IP or hostname
```

**4. Verify backend service exists:**
```bash
kubectl get svc app -n api-forge-prod
kubectl get endpoints app -n api-forge-prod
# Endpoints should list pod IPs
```

### 404 Not Found

**Cause:** Host header doesn't match any Ingress rule.

**Solution:**
```bash
# Check the configured host
kubectl describe ingress app -n api-forge-prod | grep Host

# Ensure you're using the correct hostname
curl -H "Host: api.example.com" http://<ingress-ip>/health
```

### 502 Bad Gateway

**Cause:** Backend pods not ready or service misconfiguration.

**Solution:**
```bash
# Check pods are running
kubectl get pods -n api-forge-prod -l app.kubernetes.io/name=app

# Check pod logs
kubectl logs -n api-forge-prod -l app.kubernetes.io/name=app

# Verify service targets correct port
kubectl describe svc app -n api-forge-prod
```

### TLS Certificate Issues

**1. Check TLS secret exists:**
```bash
kubectl get secret api-tls -n api-forge-prod
```

**2. If using cert-manager, check certificate status:**
```bash
kubectl get certificate -n api-forge-prod
kubectl describe certificate api-tls -n api-forge-prod
```

**3. Check cert-manager logs:**
```bash
kubectl logs -n cert-manager -l app.kubernetes.io/component=controller
```

### DNS Resolution Issues

**1. Verify DNS resolves correctly:**
```bash
nslookup api.example.com
dig api.example.com
```

**2. For local development, check /etc/hosts:**
```bash
cat /etc/hosts | grep api.local
```

**3. Test with IP directly:**
```bash
# Get the Ingress IP
kubectl get ingress -n api-forge-prod -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}'

# Curl with Host header
curl -H "Host: api.example.com" http://<ingress-ip>/health
```

### Ingress Controller Logs

```bash
# NGINX Ingress Controller logs
kubectl logs -n ingress-nginx -l app.kubernetes.io/component=controller --tail=100

# Look for errors related to your ingress
kubectl logs -n ingress-nginx -l app.kubernetes.io/component=controller | grep api-forge
```

## Tips and Best Practices

1. **Start with HTTP** - Get routing working before adding TLS
2. **Use meaningful hostnames** - Match your actual domain structure
3. **Enable SSL redirect** - Redirect HTTP to HTTPS in production
4. **Set appropriate timeouts** - Configure proxy timeouts for long-running requests
5. **Limit request size** - Use `proxy-body-size` annotation for file uploads
6. **Monitor Ingress Controller** - Set up metrics and alerting
7. **Use separate Ingress per environment** - Different hosts for staging vs production

### Common Annotations

```yaml
annotations:
  # SSL redirect (force HTTPS)
  nginx.ingress.kubernetes.io/ssl-redirect: "true"
  
  # Request body size limit
  nginx.ingress.kubernetes.io/proxy-body-size: "10m"
  
  # Timeouts for slow backends
  nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
  nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
  
  # WebSocket support
  nginx.ingress.kubernetes.io/proxy-http-version: "1.1"
  nginx.ingress.kubernetes.io/upstream-hash-by: "$http_upgrade"
  
  # Rate limiting
  nginx.ingress.kubernetes.io/limit-rps: "10"
  nginx.ingress.kubernetes.io/limit-connections: "5"
```

## Related Documentation

- [Kubernetes Deployment Guide](./fastapi-kubernetes-deployment.md) - Complete K8s deployment guide
- [Docker Dev Environment](./fastapi-docker-dev-environment.md) - Local development setup
- [Secrets Management](./security/secrets_management.md) - Managing TLS secrets
- [Production Deployment](./fastapi-production-deployment-docker-compose.md) - Docker Compose alternative

## Additional Resources

- [NGINX Ingress Controller](https://kubernetes.github.io/ingress-nginx/)
- [cert-manager Documentation](https://cert-manager.io/docs/)
- [AWS Load Balancer Controller](https://kubernetes-sigs.github.io/aws-load-balancer-controller/)
- [GKE Ingress](https://cloud.google.com/kubernetes-engine/docs/concepts/ingress)
- [Kubernetes Ingress Concepts](https://kubernetes.io/docs/concepts/services-networking/ingress/)
