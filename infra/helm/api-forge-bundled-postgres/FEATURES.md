# API Forge Bundled PostgreSQL - Feature Parity Documentation

## Overview

This standalone PostgreSQL chart provides complete feature parity with the original PostgreSQL deployment that was part of the main `api-forge` chart. It can be deployed independently for users who want to manage the database separately from the application.

## Deployment Options

### Option 1: Standalone Bundled PostgreSQL (This Chart)
```bash
uv run api-forge-cli k8s db create
```
Deploys PostgreSQL using this chart with all production features.

### Option 2: External Managed PostgreSQL
Skip this chart entirely and configure your application to connect to:
- AWS RDS
- Google Cloud SQL
- Azure Database for PostgreSQL
- Any other managed PostgreSQL service

### Option 3: Bitnami PostgreSQL (Fallback)
The CLI will fall back to Bitnami if this chart is not available (deprecated path).

## Complete Feature List

### ✅ Core Database Features
- [x] **Custom PostgreSQL Image**: Uses `app_data_postgres_image` with production optimizations
- [x] **StatefulSet Deployment**: Ensures stable network identity and ordered scaling
- [x] **Configurable Replicas**: Default 1 replica (can be increased for HA)
- [x] **Application Database**: `appdb` with 3-role security pattern
- [x] **Temporal Databases**: Optional `temporal` and `temporal_visibility` databases
- [x] **Resource Management**: CPU/memory requests and limits

### ✅ Storage & Persistence
- [x] **Data Persistence**: Dedicated PVC for PostgreSQL data (default 20Gi)
- [x] **Backup Persistence**: Separate PVC for backups (default 40Gi)
- [x] **Storage Class Configuration**: Supports custom storage classes
- [x] **Volume Claim Templates**: Automatic data volume provisioning per replica

### ✅ Security Features
- [x] **TLS/SSL Encryption**: All connections encrypted with TLS 1.2+
- [x] **Certificate Management**: Mounts server certificates from secrets
- [x] **CA Certificates**: Optional client certificate verification
- [x] **SCRAM-SHA-256 Authentication**: Modern password hashing
- [x] **Password Secrets**: All passwords stored in Kubernetes secrets
- [x] **3-Role Security Pattern**: 
  - `appowner` (NOLOGIN) - owns database/schema
  - `appuser` (LOGIN) - runtime read/write operations
  - `backupuser` (LOGIN) - read-only access
- [x] **Least Privilege**: Runtime users cannot drop database/schema
- [x] **Network Policy**: Optional pod-level access control (disabled by default, enable in production)
- [x] **Pod Security**: fsGroup configuration and seccomp profile

### ✅ Configuration Management
- [x] **PostgreSQL Configuration**: Production-optimized `postgresql.conf`
- [x] **Access Control**: Hardened `pg_hba.conf` with TLS enforcement
- [x] **Initialization Scripts**: Automated database/role setup
- [x] **Environment Variables**: Comprehensive configuration via env vars
- [x] **ConfigMap Integration**: All config files in ConfigMap

### ✅ High Availability & Reliability
- [x] **Pod Disruption Budget**: Ensures minimum 1 replica during maintenance
- [x] **Health Probes**: Liveness and readiness checks
- [x] **Ordered Updates**: RollingUpdate strategy with OrderedReady policy
- [x] **Resource Limits**: Prevents resource exhaustion
- [x] **Shared Memory**: Dedicated tmpfs for PostgreSQL shared buffers

### ✅ Initialization & Setup
- [x] **Automatic Database Creation**: Creates `appdb` on first start
- [x] **Role Management**: Creates all required roles with correct permissions
- [x] **Schema Setup**: Creates application schema with proper ownership
- [x] **Permission Grants**: Sets up all runtime and default privileges
- [x] **Extension Installation**: Installs required extensions (`btree_gin`)
- [x] **Temporal Setup** (optional): Creates Temporal databases if enabled
- [x] **Idempotent Initialization**: Safe to run multiple times

### ✅ Operational Features
- [x] **Structured Logging**: JSON logging with configurable retention
- [x] **Statement Tracking**: `pg_stat_statements` for query performance
- [x] **Connection Pooling Support**: Configurable max connections
- [x] **Backup Support**: Dedicated volume for pg_dump/pg_basebackup
- [x] **Monitoring Ready**: Exposes metrics for Prometheus integration
- [x] **Custom Entrypoint**: Universal entrypoint script with secret management

## Configuration Values

### Required Secrets

The chart requires three secrets to be created before deployment:

1. **postgres-secrets** - Database passwords
   ```bash
   kubectl create secret generic postgres-secrets \
     --from-file=postgres_password=<file> \
     --from-file=postgres_app_owner_pw=<file> \
     --from-file=postgres_app_user_pw=<file> \
     --from-file=postgres_app_ro_pw=<file> \
     --from-file=postgres_temporal_pw=<file> \
     -n api-forge-prod
   ```

2. **postgres-tls** - TLS certificates
   ```bash
   kubectl create secret generic postgres-tls \
     --from-file=server.crt=<cert-file> \
     --from-file=server.key=<key-file> \
     -n api-forge-prod
   ```

3. **postgres-ca** - CA certificate (optional, for client verification)
   ```bash
   kubectl create secret generic postgres-ca \
     --from-file=ca.crt=<ca-cert-file> \
     -n api-forge-prod
   ```

### Key Configuration Options

```yaml
postgres:
  # Image configuration
  image:
    repository: app_data_postgres_image
    tag: latest
  
  # Replica count
  replicas: 1
  
  # Database names and users
  database: appdb
  username: appuser
  
  # Resource limits
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 2000m
      memory: 4Gi
  
  # Storage configuration
  persistence:
    data:
      enabled: true
      size: 20Gi
      storageClass: ""  # Use default
    backups:
      enabled: true
      size: 40Gi
      storageClass: ""
  
  # TLS configuration
  tls:
    enabled: true
    existingSecret: postgres-tls
  
  # CA certificate (optional)
  ca:
    existingSecret: postgres-ca
  
  # Secrets reference
  secrets:
    existingSecret: postgres-secrets
  
  # High availability
  podDisruptionBudget:
    enabled: true
    minAvailable: 1
  
  # Network security (enable in production)
  networkPolicy:
    enabled: false
    ingress:
    - from:
      - podSelector:
          matchLabels:
            app.kubernetes.io/component: application
      ports:
      - protocol: TCP
        port: 5432
```

## Verification

### Chart Validation
```bash
# Render templates to verify configuration
helm template test-postgres infra/helm/api-forge-bundled-postgres/

# Install with dry-run
helm install postgres infra/helm/api-forge-bundled-postgres/ --dry-run --debug
```

### Post-Deployment Checks
```bash
# Check pod status
kubectl get pods -n api-forge-prod -l app.kubernetes.io/name=postgres

# Check StatefulSet
kubectl get statefulset postgres -n api-forge-prod

# Check PVCs
kubectl get pvc -n api-forge-prod | grep postgres

# Check service
kubectl get svc postgres -n api-forge-prod

# Test database connection
kubectl exec -it postgres-0 -n api-forge-prod -- psql -U appuser -d appdb -c "SELECT version();"
```

## Migration from Main Chart

If you previously deployed PostgreSQL as part of the main `api-forge` chart, follow these steps:

1. **Backup your data**:
   ```bash
   kubectl exec -it postgres-0 -n api-forge-prod -- pg_dump -U appuser appdb > backup.sql
   ```

2. **Uninstall main chart** (or upgrade with `postgres.enabled=false`)

3. **Deploy standalone chart**:
   ```bash
   uv run api-forge-cli k8s db create
   ```

4. **Restore data** (if needed)

5. **Update main application** to connect to standalone PostgreSQL service

## Comparison with Original

| Feature | Original (Main Chart) | Standalone Chart | Status |
|---------|----------------------|------------------|--------|
| StatefulSet | ✅ | ✅ | ✅ Complete |
| Data PVC | ✅ | ✅ | ✅ Complete |
| Backup PVC | ✅ | ✅ | ✅ Complete |
| TLS/SSL | ✅ | ✅ | ✅ Complete |
| CA Certificates | ✅ | ✅ | ✅ Complete |
| Secret Validation | ✅ | ✅ | ✅ Complete |
| ConfigMap | ✅ | ✅ | ✅ Complete |
| Service | ✅ | ✅ | ✅ Complete |
| Network Policy | ✅ | ✅ | ✅ Complete |
| Pod Disruption Budget | ✅ | ✅ | ✅ Complete |
| 3-Role Security | ✅ | ✅ | ✅ Complete |
| Temporal Support | ✅ | ✅ | ✅ Complete |
| Health Probes | ✅ | ✅ | ✅ Complete |
| Resource Limits | ✅ | ✅ | ✅ Complete |

## Known Limitations

1. **Single Replica Default**: Chart defaults to 1 replica. For true HA, consider managed PostgreSQL services or external replication solutions.

2. **No Automatic Backups**: Backup volume is provided, but backup scheduling must be configured separately.

3. **No Built-in Replication**: For multi-replica setups, additional configuration for streaming replication is needed.

4. **Manual Secret Creation**: Secrets must be created before chart deployment (not generated by chart).

## Future Enhancements

- [ ] Automated backup scheduling via CronJob
- [ ] Built-in replication support for HA
- [ ] Prometheus metrics ServiceMonitor
- [ ] Grafana dashboard ConfigMap
- [ ] pgBouncer integration for connection pooling
- [ ] Automated failover with Patroni/Stolon

## Support

For issues or questions about this standalone chart:
1. Check the main project documentation: `docs/postgres/`
2. Review deployment logs: `kubectl logs -n api-forge-prod postgres-0`
3. Open an issue in the project repository
