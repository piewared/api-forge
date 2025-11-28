# Helm Migration Plan: Complete Analysis & Implementation Strategy

**Created**: November 27, 2025  
**Purpose**: Detailed plan for migrating K8s deployments from Kustomize to Helm  
**Goal**: Enable flexible optional services with clean, maintainable templates

---

## Table of Contents

1. [Current Architecture Analysis](#current-architecture-analysis)
2. [Feature Parity Mapping](#feature-parity-mapping)
3. [Helm Chart Design](#helm-chart-design)
4. [Implementation Plan](#implementation-plan)
5. [Testing Strategy](#testing-strategy)
6. [Migration Checklist](#migration-checklist)

---

## Current Architecture Analysis

### Directory Structure

```
k8s/
├── base/
│   ├── .k8s-sources/              # Generated config files (*.k8s)
│   ├── deployments/               # 6 deployment manifests
│   │   ├── app.yaml
│   │   ├── postgres.yaml
│   │   ├── redis.yaml
│   │   ├── temporal.yaml
│   │   ├── temporal-web.yaml
│   │   └── worker.yaml
│   ├── jobs/                      # 3 initialization jobs
│   │   ├── postgres-verifier.yaml
│   │   ├── temporal-schema-setup.yaml
│   │   └── temporal-namespace-init.yaml
│   ├── services/
│   │   └── services.yaml          # All service definitions
│   ├── storage/
│   │   └── persistentvolumeclaims.yaml  # All PVC definitions
│   ├── network-policies/
│   │   └── network-policies.yaml  # All network policies
│   ├── namespace/
│   │   └── namespace.yaml
│   └── kustomization.yaml         # Resource orchestration
└── scripts/
    ├── apply-secrets.sh           # Creates K8s secrets from files
    ├── build-images.sh            # Builds Docker images
    ├── deploy-config.sh           # Syncs configs, generates ConfigMaps
    └── deploy-resources.sh        # Complete deployment orchestration
```

### Key Features & Capabilities

#### 1. **Dynamic Configuration Management**

**Current Implementation**:
- `deploy-config.sh` copies source files to `.k8s-sources/` with `.k8s` suffix
- Applies K8s-specific transformations (e.g., `APP_ENVIRONMENT=production`)
- Modifies `pg_hba.conf` to replace CIDR rules with `0.0.0.0/0` (NetworkPolicy handles security)
- Kustomize `configMapGenerator` auto-creates ConfigMaps from copied files

**Files Transformed**:
- `.env` → `.env.k8s` → `app-env` ConfigMap
- `config.yaml` → `config.yaml.k8s` → `app-config` ConfigMap
- `postgresql.conf` → `postgresql.conf.k8s` → `postgres-config` ConfigMap
- `pg_hba.conf` → `pg_hba.conf.k8s` (modified) → `postgres-config` ConfigMap
- `01-init-app.sh` → `01-init-app.sh.k8s` → `postgres-config` ConfigMap
- `verify-init.sh` → `verify-init.sh.k8s` (modified) → `postgres-verifier-config` ConfigMap
- `universal-entrypoint.sh` → `universal-entrypoint.sh.k8s` → `universal-entrypoint` ConfigMap
- `temporal/schema-setup.sh` → `temporal-schema-setup.sh.k8s` → `temporal-config` ConfigMap
- `temporal/entrypoint.sh` → `temporal-entrypoint.sh.k8s` → `temporal-config` ConfigMap

**Complexity**: Medium (bash script + sed transformations + Kustomize)

#### 2. **Secret Management**

**Current Implementation**:
- `apply-secrets.sh` reads from `infra/secrets/keys/` and `infra/secrets/certs/`
- Creates 5 K8s secrets:
  1. `postgres-secrets`: 5 password files
  2. `postgres-tls`: TLS cert/key for PostgreSQL
  3. `postgres-ca`: CA bundle + root/intermediate CAs
  4. `redis-secrets`: Redis password
  5. `app-secrets`: Session/CSRF/OIDC secrets (5 files)
- Deletes existing secrets before recreating (force update)

**Secret Mount Pattern**:
- All deployments use `volumeMounts` to mount secrets at `/run/secrets/`
- Universal entrypoint copies secrets from `/run/secrets/` to `/tmp/secrets/` or `/app/secrets/`
- Entrypoint creates environment variables from secret files

**Complexity**: Medium (bash script + file management)

#### 3. **Multi-Stage Deployment Orchestration**

**Current Implementation** (`deploy-resources.sh`):

```bash
# 10-step deployment process:
1. Prerequisites check (kubectl, cluster access)
2. Secret validation (check all secrets exist)
3. Config sync (deploy-config.sh --sync-only)
4. ConfigMap generation (via Kustomize)
5. Kustomize apply (all resources at once)
6. Core deployment restarts (pick up new images)
7. Wait for databases (PostgreSQL, Redis with rollout status)
8. Wait for Temporal schema setup (job completion)
9. Wait for Temporal server (rollout + readiness)
10. Wait for app (rollout + readiness)
```

**Features**:
- Handles immutable field errors (deletes/recreates deployments/jobs)
- Service-specific health checks with timeouts
- Rollout status tracking for each deployment
- Job completion tracking
- Detailed logging at each step

**Complexity**: High (200+ lines of bash, multiple wait loops, error handling)

#### 4. **Image Building**

**Current Implementation** (`build-images.sh`):
- Builds Docker images using `docker-compose.prod.yml` as source
- Tags images for K8s use (e.g., `api-forge-app:latest`)
- Builds: app, worker, postgres, redis, temporal (custom)

**Complexity**: Low (docker-compose wrapper)

#### 5. **Security Features**

**Network Policies**:
```yaml
postgres-ingress: Only allow app/worker/temporal pods
redis-ingress: Only allow app/worker pods
temporal-ingress: Only allow app/worker/temporal-web pods
app-ingress: Allow all (public-facing)
```

**Security Contexts**:
- Containers start as root (UID 0)
- Universal entrypoint copies secrets
- Drops privileges to non-root user via gosu/su-exec
- `readOnlyRootFilesystem: false` (some containers need write)
- Capabilities: Minimal set (CHOWN, SETUID, SETGID, DAC_OVERRIDE)
- `seccompProfile: RuntimeDefault`

**TLS**:
- PostgreSQL: TLS certificate + CA bundle verification
- Redis: Password authentication
- Temporal: Connects to PostgreSQL with TLS

**Complexity**: Medium (comprehensive but well-structured)

#### 6. **Resource Management**

**Storage**:
- PersistentVolumeClaims for all stateful services:
  - `postgres-data`: 10Gi
  - `postgres-backups`: 20Gi
  - `redis-data`: 5Gi
  - `redis-backups`: 10Gi
  - `temporal-data`: Not used (stores in PostgreSQL)

**Resource Limits**:
```yaml
postgres:    requests: 500m CPU, 512Mi RAM | limits: 2000m CPU, 2Gi RAM
redis:       requests: 250m CPU, 128Mi RAM | limits: 1000m CPU, 512Mi RAM
temporal:    requests: 500m CPU, 512Mi RAM | limits: 2000m CPU, 2Gi RAM
temporal-web: requests: 100m CPU, 128Mi RAM | limits: 500m CPU, 512Mi RAM
app:         requests: 250m CPU, 256Mi RAM | limits: 1000m CPU, 1Gi RAM
worker:      requests: 250m CPU, 256Mi RAM | limits: 1000m CPU, 1Gi RAM
```

**Complexity**: Low (standard K8s patterns)

#### 7. **Initialization Jobs**

**postgres-verifier**:
- Verifies PostgreSQL initialization succeeded
- Checks app database, users, permissions
- Validates TLS configuration
- Mounts: ConfigMap (verify-init.sh), secrets (passwords, TLS)

**temporal-schema-setup**:
- Creates Temporal database schemas (temporal, temporal_visibility)
- Uses temporalio/admin-tools image
- One-time job (doesn't restart)
- Mounts: ConfigMap (schema-setup.sh), secrets (postgres password)

**temporal-namespace-init**:
- Creates default Temporal namespace
- Runs after temporal service is healthy
- Uses temporalio/admin-tools image

**Complexity**: Medium (job dependencies, completion tracking)

#### 8. **Service Discovery**

**Services**:
```yaml
postgres:      ClusterIP,  port 5432
redis:         ClusterIP,  port 6379
temporal:      ClusterIP,  port 7233
temporal-web:  ClusterIP,  port 8080
app:           ClusterIP,  port 8000
```

**Service Naming Convention**: `{service-name}.{namespace}.svc.cluster.local`

**Environment Variables**: `enableServiceLinks: false` (prevent auto-injection conflicts)

**Complexity**: Low (standard K8s services)

#### 9. **Health Checks & Probes**

**Liveness Probes**:
- PostgreSQL: `pg_isready -U postgres`
- Redis: `redis-cli ping`
- Temporal: gRPC health probe on port 7233
- App/Worker: HTTP GET `/health` on port 8000

**Readiness Probes**:
- Similar to liveness but with shorter delays/periods
- Ensures pod receives traffic only when ready

**Startup Probes**:
- Used for slow-starting containers (PostgreSQL, Temporal)

**Complexity**: Low (standard patterns)

#### 10. **Conditional Logic (Current State)**

**Redis Conditional Deployment** (Partially Implemented):
- Python: `_prepare_kustomization()` comments out `redis.yaml` if disabled
- Bash: `REDIS_ENABLED` env var passed to `deploy-resources.sh`
- Script checks: `check_secrets()`, `restart_core_deployments()`, `wait_for_databases()`

**Limitations**:
- ❌ App/Worker still have hardcoded redis-secrets mounts
- ❌ services.yaml still contains redis service (can't conditionally remove)
- ❌ PVCs still contain redis volumes (can't conditionally remove)
- ❌ Network policies still contain redis policy (can't conditionally remove)

**Complexity**: High (fragile, requires updates in multiple places)

---

## Feature Parity Mapping

### How Helm Replaces/Improves Each Feature

| Current Feature | Current Implementation | Helm Equivalent | Complexity Reduction |
|----------------|----------------------|----------------|---------------------|
| **Config Transformation** | Bash script + sed | Go templates + values.yaml | ⬇️⬇️ Significant |
| **ConfigMap Generation** | Kustomize configMapGenerator | `helm template` with ConfigMap resources | ⬇️ Moderate |
| **Secret Management** | Bash script | Helm hooks or external-secrets operator | ⬇️ Moderate |
| **Deployment Orchestration** | 200-line bash script | Helm install/upgrade (built-in) | ⬇️⬇️⬇️ Major |
| **Image Building** | docker-compose wrapper | External (same) | → No change |
| **Conditional Resources** | Python + bash + sed | `{{- if .Values.X.enabled }}` | ⬇️⬇️⬇️ Major |
| **Resource Dependencies** | Bash wait loops | Helm hooks + Job status | ⬇️⬇️ Significant |
| **Health Checks** | Rollout status polling | Helm status + kubectl | ⬇️ Moderate |
| **Rollback** | Manual kubectl | `helm rollback` | ⬇️⬇️ Significant |
| **Versioning** | Git commits only | Helm releases + history | ⬇️⬇️ Significant |

### Helm Advantages

1. **Native Conditionals**:
   ```yaml
   {{- if .Values.redis.enabled }}
   # Entire resource definition
   {{- end }}
   ```

2. **Template Functions**:
   ```yaml
   # String manipulation
   {{ .Values.app.name | upper }}
   
   # Default values
   {{ .Values.redis.password | default "changeme" }}
   
   # Include/toYaml for DRY
   {{- include "api-forge.labels" . | nindent 4 }}
   ```

3. **Hooks for Lifecycle**:
   ```yaml
   metadata:
     annotations:
       "helm.sh/hook": pre-install,pre-upgrade
       "helm.sh/hook-weight": "5"
       "helm.sh/hook-delete-policy": before-hook-creation
   ```

4. **Built-in Rollback**:
   ```bash
   helm rollback api-forge 3  # Roll back to revision 3
   ```

5. **Release Management**:
   ```bash
   helm list                  # Show all releases
   helm history api-forge     # Show release history
   helm diff upgrade api-forge ./helm-chart  # Preview changes
   ```

6. **Values Override**:
   ```bash
   helm install api-forge ./chart \
     --set redis.enabled=false \
     --set app.replicas=3 \
     --values custom-values.yaml
   ```

---

## Helm Chart Design

### Proposed Directory Structure

```
helm/
└── api-forge/
    ├── Chart.yaml                      # Chart metadata
    ├── values.yaml                     # Default configuration
    ├── values.schema.json              # JSON schema for validation
    ├── .helmignore                     # Files to ignore
    ├── templates/
    │   ├── NOTES.txt                   # Post-install instructions
    │   ├── _helpers.tpl                # Template functions
    │   │
    │   ├── namespace.yaml              # Namespace
    │   │
    │   ├── configmaps/
    │   │   ├── app-env.yaml            # From .env
    │   │   ├── app-config.yaml         # From config.yaml
    │   │   ├── postgres-config.yaml    # PostgreSQL configs
    │   │   ├── postgres-verifier.yaml  # Verifier script
    │   │   ├── universal-entrypoint.yaml
    │   │   └── temporal-config.yaml    # Temporal scripts
    │   │
    │   ├── secrets/
    │   │   ├── postgres-secrets.yaml   # Passwords
    │   │   ├── postgres-tls.yaml       # TLS cert/key
    │   │   ├── postgres-ca.yaml        # CA bundle
    │   │   ├── redis-secrets.yaml      # Redis password
    │   │   └── app-secrets.yaml        # App secrets
    │   │
    │   ├── storage/
    │   │   ├── postgres-data-pvc.yaml
    │   │   ├── postgres-backups-pvc.yaml
    │   │   ├── redis-data-pvc.yaml
    │   │   └── redis-backups-pvc.yaml
    │   │
    │   ├── network-policies/
    │   │   ├── postgres-netpol.yaml
    │   │   ├── redis-netpol.yaml
    │   │   ├── temporal-netpol.yaml
    │   │   └── app-netpol.yaml
    │   │
    │   ├── services/
    │   │   ├── postgres-service.yaml
    │   │   ├── redis-service.yaml
    │   │   ├── temporal-service.yaml
    │   │   ├── temporal-web-service.yaml
    │   │   └── app-service.yaml
    │   │
    │   ├── deployments/
    │   │   ├── postgres.yaml
    │   │   ├── redis.yaml
    │   │   ├── temporal.yaml
    │   │   ├── temporal-web.yaml
    │   │   ├── app.yaml
    │   │   └── worker.yaml
    │   │
    │   └── jobs/
    │       ├── postgres-verifier.yaml
    │       ├── temporal-schema-setup.yaml
    │       └── temporal-namespace-init.yaml
    │
    ├── scripts/                        # External scripts (called by chart)
    │   ├── generate-secrets.sh         # Creates secrets if not exist
    │   └── build-images.sh             # Builds Docker images
    │
    └── ci/                             # Test values for CI
        ├── default-values.yaml
        ├── redis-disabled-values.yaml
        └── minimal-values.yaml
```

### values.yaml Schema

```yaml
# Global settings
global:
  namespace: api-forge-prod
  imageRegistry: ""
  imagePullPolicy: IfNotPresent
  labels:
    app.kubernetes.io/managed-by: helm
    environment: production

# PostgreSQL
postgresql:
  enabled: true
  image: app_data_postgres_image
  replicas: 1
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2000m
      memory: 2Gi
  persistence:
    data:
      enabled: true
      size: 10Gi
      storageClass: ""
    backups:
      enabled: true
      size: 20Gi
      storageClass: ""
  config:
    maxConnections: 200
    sharedBuffers: 256MB
    effectiveCacheSize: 1GB
  tls:
    enabled: true
    # Secrets will be created from files if they don't exist
  secrets:
    # Will be read from infra/secrets/keys/ if existingSecret not set
    existingSecret: ""
    postgresPassword: ""
    appOwnerPassword: ""
    appUserPassword: ""
    appRoPassword: ""
    temporalPassword: ""
  networkPolicy:
    enabled: true
    ingress:
      - from:
          - podSelector:
              matchLabels:
                app.kubernetes.io/name: app
        ports:
          - protocol: TCP
            port: 5432

# Redis
redis:
  enabled: true
  image: app_data_redis_image
  replicas: 1
  resources:
    requests:
      cpu: 250m
      memory: 128Mi
    limits:
      cpu: 1000m
      memory: 512Mi
  persistence:
    data:
      enabled: true
      size: 5Gi
      storageClass: ""
    backups:
      enabled: true
      size: 10Gi
      storageClass: ""
  config:
    maxMemory: 256mb
    maxMemoryPolicy: allkeys-lru
  secrets:
    existingSecret: ""
    password: ""
  networkPolicy:
    enabled: true
    ingress:
      - from:
          - podSelector:
              matchLabels:
                app.kubernetes.io/name: app

# Temporal
temporal:
  enabled: true
  image: my-temporal-server:1.29.0
  replicas: 1
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2000m
      memory: 2Gi
  config:
    services: "history,matching,worker,frontend"
    numHistoryShards: 64
  web:
    enabled: true
    image: temporalio/ui:latest
    replicas: 1
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 500m
        memory: 512Mi
  jobs:
    schemaSetup:
      enabled: true
      image: temporalio/admin-tools:latest
    namespaceInit:
      enabled: true
      image: temporalio/admin-tools:latest
  networkPolicy:
    enabled: true

# Application
app:
  enabled: true
  name: app
  image: api-forge-app:latest
  replicas: 1
  resources:
    requests:
      cpu: 250m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi
  env:
    APP_ENVIRONMENT: production
    APP_HOST: 0.0.0.0
    APP_PORT: "8000"
    LOG_FORMAT: json
    LOG_LEVEL: INFO
  # Environment variables from config.yaml
  config:
    fromFile: true  # Use ConfigMap from config.yaml
  # OIDC secrets
  secrets:
    existingSecret: ""
    sessionSigningSecret: ""
    csrfSigningSecret: ""
    oidc:
      google:
        clientSecret: ""
      microsoft:
        clientSecret: ""
      keycloak:
        clientSecret: ""
  service:
    type: ClusterIP
    port: 8000
  ingress:
    enabled: false
    className: nginx
    annotations: {}
    hosts:
      - host: api-forge.local
        paths:
          - path: /
            pathType: Prefix
    tls: []

# Worker
worker:
  enabled: true
  image: api-forge-app:latest
  replicas: 1
  resources:
    requests:
      cpu: 250m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi
  # Inherits most config from app

# Configuration files (will be templated into ConfigMaps)
configFiles:
  env:
    # Will be generated from .env file with K8s-specific overrides
    source: "{{ .Files.Get \".env\" }}"
    
  configYaml:
    # Will be generated from config.yaml
    source: "{{ .Files.Get \"config.yaml\" }}"
  
  postgresql:
    conf:
      source: "{{ .Files.Get \"infra/docker/prod/postgres/postgresql.conf\" }}"
    hba:
      source: "{{ .Files.Get \"infra/docker/prod/postgres/pg_hba.conf\" }}"
      # Transform for K8s (replace CIDR with 0.0.0.0/0)
      transform: true
    initScript:
      source: "{{ .Files.Get \"infra/docker/prod/postgres/init-scripts/01-init-app.sh\" }}"
    verifyScript:
      source: "{{ .Files.Get \"infra/docker/prod/postgres/verify-init.sh\" }}"
      transform: true
  
  universalEntrypoint:
    source: "{{ .Files.Get \"infra/docker/prod/scripts/universal-entrypoint.sh\" }}"
  
  temporal:
    schemaSetup:
      source: "{{ .Files.Get \"infra/docker/prod/temporal/scripts/schema-setup.sh\" }}"
    entrypoint:
      source: "{{ .Files.Get \"infra/docker/prod/temporal/scripts/entrypoint.sh\" }}"

# Jobs
jobs:
  postgresVerifier:
    enabled: true
    image: app_data_postgres_image
    backoffLimit: 3
    ttlSecondsAfterFinished: 300
  temporalSchemaSetup:
    enabled: true
    image: temporalio/admin-tools:latest
    backoffLimit: 3
    ttlSecondsAfterFinished: 300
  temporalNamespaceInit:
    enabled: true
    image: temporalio/admin-tools:latest
    backoffLimit: 3
    ttlSecondsAfterFinished: 300
```

### Template Patterns

#### Conditional Resource Inclusion

```yaml
# templates/deployments/redis.yaml
{{- if .Values.redis.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: {{ .Values.global.namespace }}
  labels:
    {{- include "api-forge.labels" . | nindent 4 }}
    app.kubernetes.io/component: cache
spec:
  # ... rest of deployment
{{- end }}
```

#### Conditional Secret Mounts

```yaml
# templates/deployments/app.yaml
volumeMounts:
  {{- if .Values.redis.enabled }}
  - name: redis-secrets
    mountPath: /run/secrets/redis_password
    subPath: redis_password
    readOnly: true
  {{- end }}
  # ... other mounts

volumes:
  {{- if .Values.redis.enabled }}
  - name: redis-secrets
    secret:
      secretName: {{ include "api-forge.redis.secretName" . }}
      defaultMode: 0400
  {{- end }}
```

#### Helper Functions (_helpers.tpl)

```yaml
{{/*
Common labels
*/}}
{{- define "api-forge.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Values.global.labels }}
{{ toYaml .Values.global.labels }}
{{- end }}
{{- end }}

{{/*
Redis secret name
*/}}
{{- define "api-forge.redis.secretName" -}}
{{- if .Values.redis.secrets.existingSecret }}
{{- .Values.redis.secrets.existingSecret }}
{{- else }}
{{- printf "%s-redis-secrets" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Postgres connection string
*/}}
{{- define "api-forge.postgres.connectionString" -}}
postgresql://{{ .Values.postgresql.username }}:{{ .Values.postgresql.password }}@postgres:5432/{{ .Values.postgresql.database }}?sslmode=require
{{- end }}
```

#### Config File Templating

```yaml
# templates/configmaps/app-env.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-env
  namespace: {{ .Values.global.namespace }}
  labels:
    {{- include "api-forge.labels" . | nindent 4 }}
data:
  # Force production mode in K8s
  APP_ENVIRONMENT: "production"
  
  # Database URLs (use service discovery)
  DATABASE_URL: "postgresql://appuser:${POSTGRES_APP_USER_PW}@postgres:5432/appdb?sslmode=require"
  
  {{- if .Values.redis.enabled }}
  REDIS_URL: "redis://:${REDIS_PASSWORD}@redis:6379"
  {{- else }}
  # Redis disabled - app will use in-memory fallback
  REDIS_URL: ""
  {{- end }}
  
  # Temporal
  {{- if .Values.temporal.enabled }}
  TEMPORAL_HOST: "temporal"
  TEMPORAL_PORT: "7233"
  TEMPORAL_NAMESPACE: "default"
  {{- end }}
  
  # Load additional env vars from values
  {{- range $key, $value := .Values.app.env }}
  {{ $key }}: {{ $value | quote }}
  {{- end }}
```

#### Helm Hooks for Jobs

```yaml
# templates/jobs/postgres-verifier.yaml
{{- if .Values.jobs.postgresVerifier.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: postgres-verifier
  namespace: {{ .Values.global.namespace }}
  labels:
    {{- include "api-forge.labels" . | nindent 4 }}
  annotations:
    # Run after postgres deployment is created
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "5"
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  backoffLimit: {{ .Values.jobs.postgresVerifier.backoffLimit }}
  ttlSecondsAfterFinished: {{ .Values.jobs.postgresVerifier.ttlSecondsAfterFinished }}
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: verifier
          image: {{ .Values.postgresql.image }}
          # ... rest of job spec
{{- end }}
```

---

## Implementation Plan

### Phase 1: Preparation (2 hours)

#### 1.1 Create Helm Chart Structure (30 min)
```bash
# Create directory structure
mkdir -p helm/api-forge/templates/{configmaps,secrets,storage,network-policies,services,deployments,jobs}
mkdir -p helm/api-forge/scripts
mkdir -p helm/api-forge/ci

# Create base files
touch helm/api-forge/Chart.yaml
touch helm/api-forge/values.yaml
touch helm/api-forge/values.schema.json
touch helm/api-forge/.helmignore
touch helm/api-forge/templates/NOTES.txt
touch helm/api-forge/templates/_helpers.tpl
```

#### 1.2 Write Chart Metadata (15 min)
```yaml
# Chart.yaml
apiVersion: v2
name: api-forge
description: Production-ready FastAPI application with PostgreSQL, Redis, and Temporal
type: application
version: 1.0.0
appVersion: "1.0.0"
keywords:
  - fastapi
  - postgresql
  - redis
  - temporal
  - python
maintainers:
  - name: API Forge Team
    email: team@api-forge.io
dependencies: []
```

#### 1.3 Create .helmignore (5 min)
```
# .helmignore
.git/
.gitignore
*.md
ci/
scripts/
```

#### 1.4 Analyze Current Secrets (15 min)
- Document all secret files in `infra/secrets/`
- Determine which should be external (not in Helm chart)
- Plan secret creation strategy (pre-install hook vs external)

#### 1.5 Design Values Schema (45 min)
- Create complete `values.yaml` with all options
- Write JSON schema for validation
- Document each value with comments
- Define service enable/disable flags

**Deliverable**: Empty Helm chart structure with metadata

---

### Phase 2: Core Templates (8 hours)

#### 2.1 Helper Functions (1 hour)
**File**: `templates/_helpers.tpl`

Create reusable template functions:
```yaml
{{/* Common labels */}}
{{- define "api-forge.labels" -}}
# ... implementation

{{/* Selector labels */}}
{{- define "api-forge.selectorLabels" -}}
# ... implementation

{{/* Service name helpers */}}
{{- define "api-forge.postgres.fullname" -}}
{{- define "api-forge.redis.fullname" -}}
{{- define "api-forge.temporal.fullname" -}}
{{- define "api-forge.app.fullname" -}}

{{/* Secret name helpers */}}
{{- define "api-forge.postgres.secretName" -}}
{{- define "api-forge.redis.secretName" -}}
{{- define "api-forge.app.secretName" -}}

{{/* ConfigMap name helpers */}}
{{- define "api-forge.app.configMapName" -}}

{{/* Image helpers */}}
{{- define "api-forge.image" -}}
{{ .Values.global.imageRegistry }}/{{ .image }}
{{- end }}

{{/* Resource name prefix */}}
{{- define "api-forge.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
```

#### 2.2 Namespace (15 min)
**File**: `templates/namespace.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: {{ .Values.global.namespace }}
  labels:
    {{- include "api-forge.labels" . | nindent 4 }}
```

#### 2.3 Storage (PVCs) (1 hour)
**Files**: `templates/storage/*.yaml`

Convert each PVC with conditional logic:
```yaml
# postgres-data-pvc.yaml
{{- if and .Values.postgresql.enabled .Values.postgresql.persistence.data.enabled }}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data
  namespace: {{ .Values.global.namespace }}
  labels:
    {{- include "api-forge.labels" . | nindent 4 }}
    app.kubernetes.io/component: database
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: {{ .Values.postgresql.persistence.data.size }}
  {{- if .Values.postgresql.persistence.data.storageClass }}
  storageClassName: {{ .Values.postgresql.persistence.data.storageClass }}
  {{- end }}
{{- end }}
```

Repeat for:
- `postgres-backups-pvc.yaml`
- `redis-data-pvc.yaml`
- `redis-backups-pvc.yaml`

#### 2.4 ConfigMaps (2 hours)
**Files**: `templates/configmaps/*.yaml`

Most complex part - convert bash transformations to Go templates:

```yaml
# app-env.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-env
  namespace: {{ .Values.global.namespace }}
  labels:
    {{- include "api-forge.labels" . | nindent 4 }}
data:
  # Force production in K8s
  APP_ENVIRONMENT: "production"
  
  # Database
  DATABASE_URL: "postgresql://appuser:${POSTGRES_APP_USER_PW}@postgres:5432/appdb?sslmode=require"
  
  # Redis
  {{- if .Values.redis.enabled }}
  REDIS_URL: "redis://:${REDIS_PASSWORD}@redis:6379"
  {{- else }}
  REDIS_URL: ""
  {{- end }}
  
  # Temporal
  {{- if .Values.temporal.enabled }}
  TEMPORAL_HOST: "temporal"
  TEMPORAL_PORT: "7233"
  {{- else }}
  TEMPORAL_HOST: ""
  {{- end }}
  
  # Merge additional env vars
  {{- range $key, $value := .Values.app.env }}
  {{ $key }}: {{ $value | quote }}
  {{- end }}
```

```yaml
# postgres-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-config
  namespace: {{ .Values.global.namespace }}
  labels:
    {{- include "api-forge.labels" . | nindent 4 }}
data:
  postgresql.conf: |
    {{ .Files.Get "files/postgresql.conf" | nindent 4 }}
  
  pg_hba.conf: |
    # K8s-optimized pg_hba.conf
    # Security enforced via NetworkPolicy
    local   all             all                                     peer
    hostssl all             postgres        127.0.0.1/32            scram-sha-256
    hostssl all             all             0.0.0.0/0               scram-sha-256
    hostnossl all           all             all                     reject
  
  01-init-app.sh: |
    {{ .Files.Get "files/01-init-app.sh" | nindent 4 }}
```

Create files in `helm/api-forge/files/`:
- Copy `postgresql.conf` as-is
- Don't need `pg_hba.conf` (templated above)
- Copy `01-init-app.sh` as-is

#### 2.5 Secrets (1 hour)
**Files**: `templates/secrets/*.yaml`

**Decision**: Secrets should be created externally, Helm only references them

```yaml
# Templates only check if secrets exist, don't create them
{{- if not .Values.postgresql.secrets.existingSecret }}
{{- fail "postgresql.secrets.existingSecret must be set" }}
{{- end }}
```

Create separate script `helm/api-forge/scripts/create-secrets.sh` (adapted from current `apply-secrets.sh`)

#### 2.6 Services (30 min)
**Files**: `templates/services/*.yaml`

Simple conversion with conditionals:
```yaml
# postgres-service.yaml
{{- if .Values.postgresql.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: {{ .Values.global.namespace }}
  labels:
    {{- include "api-forge.labels" . | nindent 4 }}
    app.kubernetes.io/component: database
spec:
  type: ClusterIP
  ports:
    - name: postgresql
      port: 5432
      targetPort: 5432
      protocol: TCP
  selector:
    {{- include "api-forge.selectorLabels" . | nindent 4 }}
    app.kubernetes.io/component: database
{{- end }}
```

#### 2.7 Network Policies (1 hour)
**Files**: `templates/network-policies/*.yaml`

```yaml
# postgres-netpol.yaml
{{- if and .Values.postgresql.enabled .Values.postgresql.networkPolicy.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: postgres-ingress
  namespace: {{ .Values.global.namespace }}
  labels:
    {{- include "api-forge.labels" . | nindent 4 }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: database
  policyTypes:
    - Ingress
  ingress:
    {{- toYaml .Values.postgresql.networkPolicy.ingress | nindent 4 }}
{{- end }}
```

#### 2.8 Deployments (2 hours)
**Files**: `templates/deployments/*.yaml`

Convert each deployment with:
1. Conditional wrapper (`{{- if .Values.X.enabled }}`)
2. Values references for images, resources, replicas
3. Conditional volume mounts (redis secrets)

```yaml
# app.yaml
{{- if .Values.app.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
  namespace: {{ .Values.global.namespace }}
  labels:
    {{- include "api-forge.labels" . | nindent 4 }}
    app.kubernetes.io/component: application
spec:
  replicas: {{ .Values.app.replicas }}
  # ... rest with values references
  
  # Volume mounts - conditional redis
  volumeMounts:
    - name: postgres-secrets
      mountPath: /run/secrets/postgres_app_user_pw
      subPath: postgres_app_user_pw
      readOnly: true
    {{- if .Values.redis.enabled }}
    - name: redis-secrets
      mountPath: /run/secrets/redis_password
      subPath: redis_password
      readOnly: true
    {{- end }}
    # ... other mounts
  
  volumes:
    - name: postgres-secrets
      secret:
        secretName: {{ include "api-forge.postgres.secretName" . }}
        defaultMode: 0400
    {{- if .Values.redis.enabled }}
    - name: redis-secrets
      secret:
        secretName: {{ include "api-forge.redis.secretName" . }}
        defaultMode: 0400
    {{- end }}
{{- end }}
```

#### 2.9 Jobs (1 hour)
**Files**: `templates/jobs/*.yaml`

Use Helm hooks for proper ordering:
```yaml
# postgres-verifier.yaml
{{- if .Values.jobs.postgresVerifier.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: postgres-verifier
  namespace: {{ .Values.global.namespace }}
  labels:
    {{- include "api-forge.labels" . | nindent 4 }}
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "5"
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  backoffLimit: {{ .Values.jobs.postgresVerifier.backoffLimit }}
  ttlSecondsAfterFinished: {{ .Values.jobs.postgresVerifier.ttlSecondsAfterFinished }}
  template:
    # ... job spec
{{- end }}
```

**Deliverable**: Complete Helm chart with all templates

---

### Phase 3: Testing & Validation (3 hours)

#### 3.1 Template Validation (30 min)
```bash
# Lint chart
helm lint helm/api-forge

# Dry-run install
helm install api-forge helm/api-forge --dry-run --debug

# Template output
helm template api-forge helm/api-forge > /tmp/manifests.yaml

# Validate K8s manifests
kubectl apply --dry-run=client -f /tmp/manifests.yaml
```

#### 3.2 Test Values (1 hour)
Create test value files in `helm/api-forge/ci/`:

```yaml
# default-values.yaml (all enabled)
redis:
  enabled: true
postgresql:
  enabled: true
temporal:
  enabled: true
```

```yaml
# redis-disabled-values.yaml
redis:
  enabled: false
postgresql:
  enabled: true
temporal:
  enabled: true
```

```yaml
# minimal-values.yaml
redis:
  enabled: false
postgresql:
  enabled: true
temporal:
  enabled: false
```

Test each:
```bash
helm template api-forge helm/api-forge -f helm/api-forge/ci/redis-disabled-values.yaml
# Verify redis resources are not present

helm template api-forge helm/api-forge -f helm/api-forge/ci/minimal-values.yaml
# Verify only postgres + app + worker
```

#### 3.3 Local Deployment Test (1 hour)
```bash
# 1. Ensure secrets exist
./helm/api-forge/scripts/create-secrets.sh api-forge-prod

# 2. Build images
./k8s/scripts/build-images.sh

# 3. Install chart
helm install api-forge helm/api-forge \
  --namespace api-forge-prod \
  --create-namespace \
  --wait \
  --timeout 10m

# 4. Verify pods
kubectl get pods -n api-forge-prod

# 5. Check app health
kubectl port-forward -n api-forge-prod svc/app 8000:8000 &
curl http://localhost:8000/health

# 6. Test with redis disabled
helm upgrade api-forge helm/api-forge \
  --set redis.enabled=false \
  --namespace api-forge-prod \
  --wait

# Verify redis pod deleted, app still works
```

#### 3.4 Document Findings (30 min)
- Record any issues encountered
- Update templates as needed
- Create troubleshooting guide

**Deliverable**: Validated Helm chart working in local cluster

---

### Phase 4: Migration Script & Documentation (2 hours)

#### 4.1 Create Migration Script (1 hour)
**File**: `scripts/migrate-to-helm.sh`

```bash
#!/bin/bash
# Migrate from Kustomize deployment to Helm

set -euo pipefail

NAMESPACE="api-forge-prod"

echo "=== Migrating to Helm ==="
echo ""

# 1. Backup current state
echo "1. Backing up current resources..."
kubectl get all -n $NAMESPACE -o yaml > backup-$(date +%Y%m%d-%H%M%S).yaml

# 2. Scale down deployments (preserve data)
echo "2. Scaling down deployments..."
kubectl scale deployment --all --replicas=0 -n $NAMESPACE

# 3. Delete Kustomize-managed resources (keep PVCs!)
echo "3. Deleting old resources (keeping PVCs)..."
kubectl delete deployment --all -n $NAMESPACE
kubectl delete service --all -n $NAMESPACE
kubectl delete configmap --all -n $NAMESPACE
kubectl delete job --all -n $NAMESPACE
kubectl delete networkpolicy --all -n $NAMESPACE

# PVCs are preserved - Helm will reuse them

# 4. Install Helm chart
echo "4. Installing Helm chart..."
helm install api-forge ./helm/api-forge \
  --namespace $NAMESPACE \
  --wait \
  --timeout 10m

echo ""
echo "=== Migration Complete ==="
echo ""
echo "Verify with:"
echo "  kubectl get pods -n $NAMESPACE"
echo "  helm list -n $NAMESPACE"
```

#### 4.2 Update Documentation (1 hour)

Create `docs/helm-usage-guide.md`:
- Installation instructions
- Customization with values
- Upgrade process
- Rollback process
- Troubleshooting

Update existing docs:
- `k8s/README.md`: Add Helm section
- `k8s/QUICKSTART.md`: Helm quick start
- `k8s/DEPLOYMENT_GUIDE.md`: Reference Helm guide

**Deliverable**: Migration script + complete documentation

---

### Phase 5: CI/CD Integration (2 hours)

#### 5.1 Update GitHub Actions (1 hour)
**File**: `.github/workflows/e2e-tests.yml`

Replace Kustomize steps with Helm:
```yaml
- name: Install Helm
  run: |
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

- name: Deploy with Helm
  run: |
    # Create secrets
    ./helm/api-forge/scripts/create-secrets.sh api-forge-prod
    
    # Install chart
    helm install api-forge ./helm/api-forge \
      --namespace api-forge-prod \
      --create-namespace \
      --wait \
      --timeout 10m

- name: Test deployment
  run: |
    # Existing tests
    kubectl get pods -n api-forge-prod
    # ... health checks

- name: Test Redis disabled
  run: |
    helm upgrade api-forge ./helm/api-forge \
      --set redis.enabled=false \
      --namespace api-forge-prod \
      --wait
    
    # Verify app still works
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=app -n api-forge-prod --timeout=300s
```

#### 5.2 Update CLI Commands (1 hour)
**File**: `src/cli/deployment/k8s_deployer.py`

Add Helm support:
```python
class K8sDeployer(BaseDeployer):
    def __init__(self, console: Console, project_root: Path, use_helm: bool = True):
        self.use_helm = use_helm
        self.helm_chart = project_root / "helm" / "api-forge"
    
    def deploy(self, **kwargs: Any) -> None:
        if self.use_helm:
            self._deploy_with_helm(**kwargs)
        else:
            self._deploy_with_kustomize(**kwargs)  # Legacy
    
    def _deploy_with_helm(self, **kwargs):
        # Build images
        self._build_images()
        
        # Create secrets
        self._create_secrets_with_script()
        
        # Helm install/upgrade
        values = self._build_helm_values(**kwargs)
        self.run_command([
            "helm", "upgrade", "--install", "api-forge",
            str(self.helm_chart),
            "--namespace", namespace,
            "--create-namespace",
            "--wait",
            "--timeout", "10m",
            *values
        ])
    
    def _build_helm_values(self, **kwargs):
        """Build --set flags from config.yaml"""
        from .service_config import is_redis_enabled
        
        values = []
        if not is_redis_enabled():
            values.extend(["--set", "redis.enabled=false"])
        
        # Add more conditional values
        return values
```

**Deliverable**: CI/CD pipeline using Helm

---

### Phase 6: Cleanup & Polish (1 hour)

#### 6.1 Remove Old Kustomize Files (15 min)
```bash
# Move to legacy folder (don't delete yet)
mkdir k8s-legacy
mv k8s/base k8s-legacy/
mv k8s/scripts/*.sh k8s-legacy/scripts/

# Keep only:
# - k8s/docs (update them)
# - k8s/README.md (update it)
```

#### 6.2 Update .gitignore (5 min)
```
# Helm
helm/api-forge/charts/
helm/api-forge/*.tgz

# Keep legacy for reference
k8s-legacy/
```

#### 6.3 Final Documentation Review (30 min)
- Proofread all docs
- Ensure examples work
- Add troubleshooting section
- Create video/GIF of deployment

#### 6.4 Announce Migration (10 min)
- Update main README
- Add migration notice
- Document benefits

**Deliverable**: Clean, production-ready Helm chart

---

## Testing Strategy

### Test Scenarios

#### 1. Default Deployment (All Services)
```bash
helm install api-forge helm/api-forge
# Expect: All 6 deployments, all services, all PVCs
```

#### 2. Redis Disabled
```bash
helm install api-forge helm/api-forge --set redis.enabled=false
# Expect: 5 deployments (no redis), no redis PVC, app works with in-memory cache
```

#### 3. Temporal Disabled
```bash
helm install api-forge helm/api-forge --set temporal.enabled=false
# Expect: 4 deployments (no temporal, temporal-web), app works without workflows
```

#### 4. Minimal (Only App + PostgreSQL)
```bash
helm install api-forge helm/api-forge \
  --set redis.enabled=false \
  --set temporal.enabled=false
# Expect: 2 deployments (postgres, app), no temporal-web, no redis
```

#### 5. Custom Values
```bash
helm install api-forge helm/api-forge \
  --set app.replicas=3 \
  --set postgresql.resources.limits.memory=4Gi \
  --set redis.persistence.data.size=20Gi
# Expect: Scaled resources, larger PVC
```

#### 6. Upgrade with Config Change
```bash
helm install api-forge helm/api-forge
# Change config.yaml
helm upgrade api-forge helm/api-forge --reuse-values
# Expect: ConfigMap updated, pods restarted
```

#### 7. Rollback
```bash
helm install api-forge helm/api-forge
helm upgrade api-forge helm/api-forge --set redis.enabled=false
helm rollback api-forge
# Expect: Redis comes back, no data loss
```

### Validation Checklist

For each test:
- [ ] All expected pods running
- [ ] All expected services created
- [ ] ConfigMaps have correct data
- [ ] Secrets mounted correctly
- [ ] Health checks pass
- [ ] App `/health` endpoint returns 200
- [ ] Logs show no errors
- [ ] Data persists across upgrades
- [ ] `helm list` shows correct release
- [ ] `helm status` shows healthy

---

## Migration Checklist

### Pre-Migration
- [ ] Review all current deployments
- [ ] Document custom configurations
- [ ] Backup all secrets (infra/secrets/)
- [ ] Test current deployment end-to-end
- [ ] Create rollback plan

### Helm Chart Creation
- [ ] Phase 1: Preparation (2h)
  - [ ] Create directory structure
  - [ ] Write Chart.yaml
  - [ ] Design values.yaml
  - [ ] Create helper functions
- [ ] Phase 2: Core Templates (8h)
  - [ ] Namespace
  - [ ] Storage (PVCs)
  - [ ] ConfigMaps
  - [ ] Secrets (reference only)
  - [ ] Services
  - [ ] Network Policies
  - [ ] Deployments
  - [ ] Jobs with hooks
- [ ] Phase 3: Testing (3h)
  - [ ] Lint chart
  - [ ] Dry-run install
  - [ ] Test all value combinations
  - [ ] Local deployment test
- [ ] Phase 4: Migration Script (2h)
  - [ ] Write migration script
  - [ ] Update documentation
  - [ ] Create usage guide
- [ ] Phase 5: CI/CD (2h)
  - [ ] Update GitHub Actions
  - [ ] Update CLI commands
- [ ] Phase 6: Cleanup (1h)
  - [ ] Archive Kustomize files
  - [ ] Update .gitignore
  - [ ] Final documentation

### Post-Migration
- [ ] Deploy to production
- [ ] Monitor for issues
- [ ] Update team training
- [ ] Archive old deployment method
- [ ] Celebrate! 🎉

**Total Estimated Time**: 18 hours (2-3 working days)

---

## Benefits Summary

| Aspect | Before (Kustomize) | After (Helm) | Time Saved |
|--------|-------------------|-------------|-----------|
| **Add optional service** | 2-3 hours | 30 minutes | 1.5-2.5 hours |
| **Deploy to new cluster** | 30+ minutes | 5 minutes | 25+ minutes |
| **Rollback deployment** | Manual kubectl | `helm rollback` | 10+ minutes |
| **View deployment history** | Git commits | `helm history` | Instant |
| **Conditional resources** | Python + Bash + sed | `{{- if }}` | N/A (complexity) |
| **Secret mounts** | Hardcoded + overlays | Template conditionals | N/A (maintainability) |
| **Config updates** | Bash script + deploy | `helm upgrade` | 5-10 minutes |
| **Test different configs** | Change files + deploy | `--set` flags | Instant |

**Total time savings per year** (assuming 10 optional services, 50 deployments):
- Optional service implementation: **15-20 hours**
- Deployment operations: **20+ hours**
- Debugging/maintenance: **30+ hours**
- **Total: 65-70 hours saved per year**

---

## Conclusion

Helm migration is a significant but worthwhile investment:

1. **Initial Cost**: 18 hours (2-3 days)
2. **Payback Period**: ~3 months (based on time savings)
3. **Long-term Benefits**: 
   - Cleaner architecture
   - Easier maintenance
   - Better scalability
   - Industry standard practices
   - Reduced cognitive load

**Recommendation**: Proceed with Helm migration before implementing more optional services.

---

**Document Version**: 1.0  
**Status**: Ready for Implementation  
**Next Step**: Begin Phase 1 - Preparation
