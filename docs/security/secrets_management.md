# Secrets Management

This document provides comprehensive guidance on managing secrets in the application infrastructure, including password generation, PKI certificate management, and Docker Compose integration.

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Secrets Generated](#secrets-generated)
4. [PKI Certificate Management](#pki-certificate-management)
5. [Script Usage](#script-usage)
6. [Docker Compose Integration](#docker-compose-integration)
7. [Backup and Restore](#backup-and-restore)
8. [Security Best Practices](#security-best-practices)
9. [Deployment Scenarios](#deployment-scenarios)
10. [Troubleshooting](#troubleshooting)

## Overview

The application uses a centralized secrets management system based on file-based secrets stored in the `./infra/secrets/` directory. The `infra/secrets/generate_secrets.sh` script is the central tool for managing all application secrets and certificates.

### Key Features

- ✅ **Cryptographically secure** password generation using OpenSSL and `/dev/urandom`
- ✅ **Complete PKI infrastructure** with root and intermediate CAs
- ✅ **Comprehensive TLS certificates** with Docker and Fly.io SANs
- ✅ **Automated backup** of existing secrets with timestamped directories
- ✅ **Permission management** (600 for keys, 644 for certificates)
- ✅ **Verification tools** for secret validation
- ✅ **Docker Compose integration** with native secrets management
- ✅ **Universal entrypoint** for secure secret handling in containers

## Quick Start

### First-Time Setup

```bash
# 1. Generate all secrets and PKI certificates
./infra/secrets/generate_secrets.sh --generate-pki

# 2. Verify generation
./infra/secrets/generate_secrets.sh --verify

# 3. List all generated files
./infra/secrets/generate_secrets.sh --list
```

### Common Operations

```bash
# Generate only application secrets (no PKI)
./infra/secrets/generate_secrets.sh

# Generate only PKI certificates (preserves existing secrets)
./infra/secrets/generate_secrets.sh --generate-pki

# Verify all secrets meet security requirements
./infra/secrets/generate_secrets.sh --verify

# Create manual backup before changes
./infra/secrets/generate_secrets.sh --backup-only

# Force overwrite without backup (use with caution)
./infra/secrets/generate_secrets.sh --force

# Show help
./infra/secrets/generate_secrets.sh --help
```

## Secrets Generated

### Directory Structure

```
infra/secrets/
├── user-provided.env.example      # Template for deterministic secrets (not committed)
├── user-provided.env              # Your filled-in deterministic secrets (gitignored)
├── keys/                           # Application passwords and secrets
│   ├── postgres_password.txt
│   ├── postgres_app_user_pw.txt
│   ├── postgres_app_owner_pw.txt
│   ├── postgres_app_ro_pw.txt
│   ├── postgres_temporal_pw.txt
│   ├── redis_password.txt
│   ├── session_signing_secret.txt
│   ├── csrf_signing_secret.txt
├── certs/                          # PKI certificates and keys
│   ├── root-ca.crt                # Root Certificate Authority (public)
│   ├── root-ca.key                # Root CA private key (sensitive)
│   ├── root-ca.srl                # Root CA serial number tracker
│   ├── intermediate-ca.crt        # Intermediate Certificate Authority (public)
│   ├── intermediate-ca.key        # Intermediate CA private key (sensitive)
│   ├── intermediate-ca.srl        # Intermediate CA serial number tracker
│   ├── ca-bundle.crt              # CA bundle for client cert validation
│   ├── postgres/                  # PostgreSQL TLS certificates
│   ├── redis/                     # Redis TLS certificates
│   └── temporal/                  # Temporal TLS certificates
└── backup_YYYYMMDD_HHMMSS/        # Automatic backups
```

### Application Secrets (keys/)

All secrets are stored with 600 permissions (owner read/write only).

| File | Purpose | Format | Security Level |
|------|---------|--------|----------------|
| `postgres_password.txt` | PostgreSQL superuser password | 24 chars | **Critical** |
| `postgres_app_user_pw.txt` | Application database user password | 24 chars | **High** |
| `postgres_app_owner_pw.txt` | Database owner user password | 24 chars | **High** |
| `postgres_app_ro_pw.txt` | Read-only database user password | 24 chars | **Medium** |
| `postgres_temporal_pw.txt` | Temporal database user password | 24 chars | **High** |
| `redis_password.txt` | Redis authentication password | 24 chars | **High** |
| `session_signing_secret.txt` | JWT session signing key | 32 bytes base64 | **Critical** |
| `csrf_signing_secret.txt` | CSRF protection secret | 32 bytes base64 | **High** |

**Deterministic OIDC Secrets**: When you run `./infra/secrets/generate_secrets.sh`, the script now
prompts for (or reads via `--user-secrets-file`/CLI flags) the `OIDC_GOOGLE_CLIENT_SECRET`,
`OIDC_MICROSOFT_CLIENT_SECRET`, and `OIDC_KEYCLOAK_CLIENT_SECRET`. The provided values are written to
`infra/secrets/keys/oidc_*_client_secret.txt`, so Kubernetes and Docker deployments consume them just
like every other secret. `infra/secrets/user-provided.env` remains as an optional input source for
non-interactive workflows—populate it from the `.example` template if you’d rather not type secrets
manually, but the runtime never reads that file directly anymore.

**Password Format**: 24-character string with uppercase, lowercase, numbers, and safe special characters (`!@#$%^&*()_+-=`)

**Signing Secret Format**: Base64-encoded cryptographic keys (256-bit for session/CSRF, 384-bit for OIDC)

**Usage Example**:
```bash
# Load secrets into environment variables
export POSTGRES_PASSWORD=$(cat infra/secrets/keys/postgres_password.txt)
export REDIS_PASSWORD=$(cat infra/secrets/keys/redis_password.txt)
export SESSION_SIGNING_SECRET=$(cat infra/secrets/keys/session_signing_secret.txt)
```

## PKI Certificate Management

### Certificate Hierarchy

The PKI system uses a three-tier certificate hierarchy:

```
Root CA (10 years, 4096-bit)
└── Intermediate CA (5 years, 4096-bit, pathlen:0)
    ├── PostgreSQL Certificate (1 year, 2048-bit)
    ├── Redis Certificate (1 year, 2048-bit)
    └── Temporal Certificate (1 year, 2048-bit)
```

### Certificate Files

#### Root Certificate Authority

| File | Purpose | Validity | Key Size |
|------|---------|----------|----------|
| `root-ca.crt` | Root CA public certificate | 10 years | 4096-bit RSA |
| `root-ca.key` | Root CA private key | - | 4096-bit RSA |
| `root-ca.srl` | Root CA serial number tracker | - | Text file |

#### Intermediate Certificate Authority

| File | Purpose | Validity | Key Size |
|------|---------|----------|----------|
| `intermediate-ca.crt` | Intermediate CA public certificate | 5 years | 4096-bit RSA |
| `intermediate-ca.key` | Intermediate CA private key | - | 4096-bit RSA |
| `intermediate-ca.srl` | Intermediate CA serial number tracker | - | Text file |

#### CA Bundle

| File | Purpose | Contents |
|------|---------|----------|
| `ca-bundle.crt` | Client certificate validation | Intermediate CA + Root CA |

#### Service Certificates (per service: postgres, redis, temporal)

Each service directory contains:

| File | Purpose | Validity | Key Size |
|------|---------|----------|----------|
| `server.crt` | Service certificate only | 1 year | 2048-bit RSA |
| `server.key` | Service private key | - | 2048-bit RSA |
| `server-chain.crt` | Full certificate chain (with root CA) | - | Combined |
| `server-chain-no-root.crt` | Chain without root CA | - | Combined |

### Certificate Serial Numbers (.srl files)

The `.srl` files are **certificate serial number trackers** that maintain the next serial number to be assigned by each Certificate Authority.

**Purpose**:
- **Unique identification**: Each certificate must have a unique serial number within a CA
- **Certificate revocation**: Serial numbers are used in Certificate Revocation Lists (CRLs)
- **Audit trails**: Track the sequence of certificate issuance
- **Standards compliance**: Required by X.509 certificate standards

**Contents**: Single line containing the next serial number in hexadecimal format

**Example**:
```bash
# View current serial number
cat infra/secrets/certs/root-ca.srl
# Output: 1000000000000002
```

**⚠️ Important**: NEVER delete these files - serial number collisions can break PKI trust. Always backup `.srl` files with CA keys.

### Certificate Chain Options

#### Full Chain (server-chain.crt)

**Contents**: Service Certificate + Intermediate CA + Root CA

**When to use**:
- ✅ Internal PKI deployments
- ✅ Docker container services
- ✅ Simplified deployment (self-contained)

**Example Configuration**:
```bash
# PostgreSQL
ssl_cert_file = '/certs/server-chain.crt'
ssl_key_file = '/certs/server.key'
```

#### Chain Without Root (server-chain-no-root.crt)

**Contents**: Service Certificate + Intermediate CA only

**When to use**:
- ✅ Public CA practices
- ✅ Root CA managed in system trust store
- ✅ Easier root CA rotation

**Example Configuration**:
```bash
# PostgreSQL
ssl_cert_file = '/certs/server-chain-no-root.crt'
ssl_key_file = '/certs/server.key'
ssl_ca_file = '/certs/ca-bundle.crt'
```

### Subject Alternative Names (SANs)

Service certificates include comprehensive SANs for different deployment scenarios:

**PostgreSQL**:
- DNS: `postgres`, `postgres.backend`, `app_data_postgres_db`, `database`, `db`, `localhost`, `*.fly.dev`, `*.internal`
- IP: `127.0.0.1`, `::1`

**Redis**:
- DNS: `redis`, `redis.backend`, `cache`, `localhost`, `*.fly.dev`, `*.internal`
- IP: `127.0.0.1`, `::1`

**Temporal**:
- DNS: `temporal`, `temporal.backend`, `temporal-server`, `workflow`, `localhost`, `*.fly.dev`, `*.internal`
- IP: `127.0.0.1`, `::1`

### Certificate Extensions

#### Root CA
- `basicConstraints = critical, CA:TRUE`
- `keyUsage = critical, keyCertSign, cRLSign`
- `subjectKeyIdentifier = hash`
- `authorityKeyIdentifier = keyid:always,issuer:always`

#### Intermediate CA
- `basicConstraints = critical, CA:TRUE, pathlen:0`
- `keyUsage = critical, keyCertSign, cRLSign`
- `subjectKeyIdentifier = hash`
- `authorityKeyIdentifier = keyid:always,issuer:always`

#### Service Certificates
- `basicConstraints = CA:FALSE`
- `keyUsage = critical, digitalSignature, keyEncipherment`
- `extendedKeyUsage = serverAuth, clientAuth`
- `subjectKeyIdentifier = hash`
- `authorityKeyIdentifier = keyid:always,issuer:always`
- `subjectAltName = [comprehensive DNS and IP names]`

### Certificate Renewal

Service certificates expire after 1 year and should be renewed:

```bash
# Regenerate service certificates only (preserves existing CAs)
./infra/secrets/generate_secrets.sh --generate-pki

# Restart services to apply new certificates
docker-compose -f docker-compose.prod.yml restart postgres redis temporal
```

**⚠️ Emergency CA Regeneration** (invalidates all service certificates):
```bash
./infra/secrets/generate_secrets.sh --generate-pki --force-ca

# All services must be restarted
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d
```

### Certificate Verification

```bash
# Verify all secrets and certificates
./infra/secrets/generate_secrets.sh --verify

# Manual certificate inspection
openssl x509 -in infra/secrets/certs/postgres/server.crt -text -noout

# Verify certificate chain
openssl verify -CAfile infra/secrets/certs/root-ca.crt \
  -untrusted infra/secrets/certs/intermediate-ca.crt \
  infra/secrets/certs/postgres/server.crt
```

## Script Usage

### Command-Line Options

```bash
./infra/secrets/generate_secrets.sh [OPTIONS]

Options:
  -h, --help           Show help message
  -f, --force          Overwrite existing secrets without backup
  -b, --backup-only    Only backup existing secrets, don't generate new ones
  -v, --verify         Verify existing secrets meet security requirements
  -l, --list           List all secret files and their sizes
  -p, --generate-pki   Generate PKI certificates
  --force-ca           Force regeneration of CA certificates (use with caution)
```

### Usage Patterns

#### Initial Setup (New Project)

```bash
# Generate all secrets and PKI certificates
./infra/secrets/generate_secrets.sh --generate-pki

# Verify generation
./infra/secrets/generate_secrets.sh --verify
```

#### Rotate All Secrets

```bash
# Regenerate all secrets (automatically backs up old ones)
./infra/secrets/generate_secrets.sh

# Verify new secrets
./infra/secrets/generate_secrets.sh --verify

# Restart services
docker-compose -f docker-compose.prod.yml restart
```

#### Annual Certificate Renewal

```bash
# Regenerate service certificates (preserves CA certificates)
./infra/secrets/generate_secrets.sh --generate-pki

# Restart affected services
docker-compose -f docker-compose.prod.yml restart postgres redis temporal
```

## Docker Compose Integration

### Development Environment (docker-compose.dev.yml)

Development environment uses hardcoded credentials for simplicity:

```yaml
services:
  postgres:
    environment:
      POSTGRES_PASSWORD: devpass
      POSTGRES_USER: devuser
```

### Test Environment (docker-compose.test.yml)

Test environment uses Docker Compose native secrets management:

```yaml
services:
  postgres:
    secrets:
      - postgres_password
      - postgres_app_owner_pw
      - postgres_app_user_pw
      - postgres_app_ro_pw
      - source: postgres_tls_cert
        target: server.crt
        mode: 0400
      - source: postgres_tls_key
        target: server.key
        mode: 0400

secrets:
  postgres_password:
    file: ./infra/secrets/keys/postgres_password.txt
  postgres_tls_cert:
    file: ./infra/secrets/certs/postgres/server.crt
  postgres_tls_key:
    file: ./infra/secrets/certs/postgres/server.key
```

**Universal Entrypoint Integration**:

```yaml
environment:
  SECRETS_SOURCE_DIR: /run/secrets      # Docker secrets mount point
  SECRETS_TARGET_DIR: /app/secrets      # Application secrets directory
  CERTS_TARGET_DIR: /etc/postgresql/ssl # Certificate target directory
  CREATE_ENV_VARS: "true"              # Create environment variables
  SKIP_USER_SWITCH: "false"            # Enable user switching
```

### Production Environment (docker-compose.prod.yml)

Production uses a hybrid approach with volume mounts and tmpfs:

```yaml
services:
  app:
    volumes:
      # Mount host secrets (readable by root)
      - ./infra/secrets:/mnt/host_secrets:ro
    tmpfs:
      # Secure tmpfs for runtime secrets (owned by appuser)
      - /run/secrets:rw,noexec,nosuid,nodev,size=64k,uid=1001,gid=1001
```

**Security Features**:
- **Volume mounts**: Host secrets mounted read-only
- **tmpfs**: Runtime secrets in memory-only filesystem
- **User isolation**: Secrets owned by application user (uid 1001)
- **Restricted permissions**: `noexec`, `nosuid`, `nodev` flags

### Secret Access Patterns

#### In Containers

Secrets are accessible via multiple methods:

**1. File-based (recommended)**:
```bash
POSTGRES_PASSWORD=$(cat /run/secrets/postgres_password)
```

**2. Environment variables** (when `CREATE_ENV_VARS=true`):
```bash
echo $POSTGRES_PASSWORD
```

**3. Application configuration** (Python example):
```python
with open('/run/secrets/postgres_password') as f:
    password = f.read().strip()
```

#### Service Configuration Examples

**PostgreSQL TLS**:
```yaml
services:
  postgres:
    volumes:
      - ./infra/secrets/certs/postgres/server-chain.crt:/certs/server.crt:ro
      - ./infra/secrets/certs/postgres/server.key:/certs/server.key:ro
    command: |
      postgres
        -c ssl=on
        -c ssl_cert_file=/certs/server.crt
        -c ssl_key_file=/certs/server.key
```

**Redis TLS**:
```yaml
services:
  redis:
    volumes:
      - ./infra/secrets/certs/redis/server-chain.crt:/certs/server.crt:ro
      - ./infra/secrets/certs/redis/server.key:/certs/server.key:ro
    command: |
      redis-server
        --tls-port 6379
        --port 0
        --tls-cert-file /certs/server.crt
        --tls-key-file /certs/server.key
```

**FastAPI Application**:
```yaml
services:
  app:
    environment:
      - SESSION_SIGNING_SECRET_FILE=/run/secrets/session_signing_secret
      - CSRF_SIGNING_SECRET_FILE=/run/secrets/csrf_signing_secret
    secrets:
      - session_signing_secret
      - csrf_signing_secret

secrets:
  session_signing_secret:
    file: ./infra/secrets/keys/session_signing_secret.txt
  csrf_signing_secret:
    file: ./infra/secrets/keys/csrf_signing_secret.txt
```

## Backup and Restore

### Automatic Backups

The script automatically backs up existing secrets before generating new ones:

```bash
# Run script - automatic backup created
./infra/secrets/generate_secrets.sh
# [INFO] Backing up existing secrets to: infra/secrets/backup_20241102_143022

# Backups preserve complete directory structure
ls -la infra/secrets/backup_20241102_143022/
# drwx------  keys/
# drwxr-xr-x  certs/
```

### Backup Structure

```
infra/secrets/backup_YYYYMMDD_HHMMSS/
├── keys/
│   ├── postgres_password.txt
│   ├── redis_password.txt
│   └── ...
└── certs/
    ├── root-ca.crt
    ├── root-ca.key
    ├── root-ca.srl
    ├── postgres/
    │   ├── server.crt
    │   └── server.key
    └── ...
```

### Restore from Backup

```bash
# 1. Stop all services
docker-compose -f docker-compose.prod.yml down

# 2. List available backups
ls -d infra/secrets/backup_*

# 3. Restore specific backup
BACKUP_DIR="infra/secrets/backup_20241102_143022"
cp -r "$BACKUP_DIR/keys/"* infra/secrets/keys/
cp -r "$BACKUP_DIR/certs/"* infra/secrets/certs/

# 4. Fix permissions
chmod 600 infra/secrets/keys/*
chmod 600 infra/secrets/certs/*/server.key
chmod 644 infra/secrets/certs/*/*.crt

# 5. Verify restore
./infra/secrets/generate_secrets.sh --verify

# 6. Restart services
docker-compose -f docker-compose.prod.yml up -d
```

### Disaster Recovery

If secrets directory is corrupted or lost:

```bash
# 1. Stop all services
docker-compose -f docker-compose.prod.yml down

# 2. Find most recent backup
ls -lt infra/secrets/backup_* | head -1

# 3. Restore from backup (see above)

# 4. Verify integrity
./infra/secrets/generate_secrets.sh --verify

# 5. Restart services
docker-compose -f docker-compose.prod.yml up -d
```

## Security Best Practices

### File Permissions

The script automatically sets proper permissions:

- **Private Keys** (`.key` files): `600` (owner read/write only)
- **Certificates** (`.crt` files): `644` (owner read/write, others read)
- **Secrets** (`keys/*.txt` files): `600` (owner read/write only)

**Verify Permissions**:
```bash
# Check key permissions
ls -la infra/secrets/keys/
# All files should show: -rw------- (600)

# Check certificate permissions
ls -la infra/secrets/certs/postgres/
# .crt files: -rw-r--r-- (644)
# .key files: -rw------- (600)
```

**Fix Permissions** (if needed):
```bash
chmod 600 infra/secrets/keys/*.txt
chmod 600 infra/secrets/certs/*/*.key
chmod 644 infra/secrets/certs/*/*.crt
```

### Version Control

**NEVER commit secrets to Git!**

Ensure `.gitignore` includes:
```gitignore
# Secrets and certificates
infra/secrets/keys/
infra/secrets/certs/
infra/secrets/backup_*/
*.key
*.crt
*.csr
*.srl
*_password.txt
*_secret.txt
```

**Verify Nothing is Tracked**:
```bash
git ls-files | grep -E '(\.key|\.crt|password\.txt|secret\.txt)'
# (Should return nothing)
```

### Password Security

- **Minimum lengths**: 24 characters for database passwords, 32+ bytes for signing secrets
- **Character sets**: Mixed case, numbers, safe special characters
- **Generation**: Cryptographically secure random generation using OpenSSL
- **Storage**: File-based with restrictive permissions (600)

### Certificate Security

- **Key sizes**: 4096-bit for CAs, 2048-bit for service certificates
- **Validity periods**: Long for CAs (5-10 years), short for services (1 year)
- **Path length constraints**: Intermediate CA has `pathlen:0` to prevent sub-CA creation
- **Extensions**: Appropriate key usage and extended key usage
- **Serial number integrity**: `.srl` files must be preserved to prevent serial collisions
- **Serial number backup**: Include `.srl` files in CA backup procedures

### Secret Storage

**Development**:
- Store in `infra/secrets/` directory (gitignored)
- Use `.env` file for environment variables
- Acceptable to store plaintext on developer machine

**Production**:
- Use secrets management service (AWS Secrets Manager, HashiCorp Vault, etc.)
- Mount secrets via Docker secrets or Kubernetes secrets
- Encrypt at rest using OS-level encryption
- Rotate regularly (every 90 days)

### Rotation Schedule

| Secret Type | Rotation Frequency | Reason |
|-------------|-------------------|--------|
| Database Passwords | Every 90 days | Limit exposure window |
| Redis Password | Every 90 days | Limit exposure window |
| Session/CSRF Secrets | Every 90 days | Prevent token forgery |
| OIDC Client Secrets | When provider rotates | Provider policy |
| Service Certificates | Annually | Certificate expiration |
| Intermediate CA | Every 5 years | Certificate expiration |
| Root CA | Every 10 years | Certificate expiration |

**Emergency Rotation**:
Rotate immediately if:
- Security breach or compromise suspected
- Secret accidentally committed to version control
- Employee with access leaves organization
- Compliance audit requires rotation

### Access Control

**Who Should Have Access**:
- ✅ DevOps/SRE team (full access to all secrets)
- ✅ Senior developers (read access for debugging)
- ✗ Junior developers (no direct access, use development environment)
- ✗ Contractors (no access to production secrets)

**Audit Access**:
```bash
# Check who can read secrets
ls -l infra/secrets/keys/

# Check file access logs (Linux)
sudo ausearch -f /path/to/infra/secrets/keys/postgres_password.txt

# Review backup history
ls -lt infra/secrets/backup_*
```

## Deployment Scenarios

### Development Environment

```bash
# Generate all secrets for development
./infra/secrets/generate_secrets.sh --generate-pki

# Start development environment (uses hardcoded credentials)
docker-compose -f docker-compose.dev.yml up
```

### Test Environment

```bash
# Generate all secrets and certificates
./infra/secrets/generate_secrets.sh --generate-pki

# Start test environment (uses Docker secrets)
docker-compose -f docker-compose.test.yml up
```

### Production Environment

```bash
# Generate production secrets
./infra/secrets/generate_secrets.sh --generate-pki

# Verify security
./infra/secrets/generate_secrets.sh --verify

# Deploy to production
docker-compose -f docker-compose.prod.yml up -d
```

### Fly.io Deployment

The certificates include `*.fly.dev` SANs for Fly.io compatibility:

```bash
# Certificates already include Fly.io SANs
# No additional configuration needed
fly deploy
```

### Kubernetes Deployment

Convert file-based secrets to Kubernetes secrets:

```bash
# Create Kubernetes secrets from files
kubectl create secret generic postgres-secrets \
  --from-file=password=infra/secrets/keys/postgres_password.txt \
  --from-file=app-user-pw=infra/secrets/keys/postgres_app_user_pw.txt

kubectl create secret tls postgres-tls \
  --cert=infra/secrets/certs/postgres/server-chain.crt \
  --key=infra/secrets/certs/postgres/server.key

kubectl create secret generic redis-password \
  --from-file=password=infra/secrets/keys/redis_password.txt

kubectl create secret tls redis-tls \
  --cert=infra/secrets/certs/redis/server-chain.crt \
  --key=infra/secrets/certs/redis/server.key
```

## Troubleshooting

### Common Issues

#### Permission Denied Running Script

```bash
# Error:
bash: ./infra/secrets/generate_secrets.sh: Permission denied
```

**Solution**:
```bash
chmod +x infra/secrets/generate_secrets.sh
./infra/secrets/generate_secrets.sh
```

#### OpenSSL Not Found

```bash
# Error:
[ERROR] Missing required dependencies: openssl
```

**Solution**:
```bash
# Ubuntu/Debian
sudo apt-get install openssl

# macOS
brew install openssl

# Verify installation
openssl version
```

#### Certificate Expired

```bash
# Check certificate expiration
openssl x509 -in infra/secrets/certs/postgres/server.crt -noout -enddate
# notAfter=Nov  2 14:30:22 2024 GMT (expired!)
```

**Solution**:
```bash
# Regenerate service certificates (preserves CA)
./infra/secrets/generate_secrets.sh --generate-pki

# Restart affected services
docker-compose -f docker-compose.prod.yml restart postgres redis temporal
```

#### CA Certificate Expired

```bash
# Check CA expiration
openssl x509 -in infra/secrets/certs/intermediate-ca.crt -noout -enddate
# notAfter=Nov  2 14:30:22 2024 GMT (expired!)
```

**Solution** (⚠️ requires regenerating ALL certificates):
```bash
# Backup current setup
./infra/secrets/generate_secrets.sh --backup-only

# Regenerate entire PKI hierarchy
./infra/secrets/generate_secrets.sh --generate-pki --force-ca

# Restart all services
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d
```

#### Secret Too Short

```bash
# Verification shows:
[ERROR] keys/redis_password.txt: Too short (12 bytes, minimum: 16)
```

**Solution**:
```bash
# Regenerate all secrets
./infra/secrets/generate_secrets.sh

# Or regenerate specific secret manually
openssl rand -base64 24 > infra/secrets/keys/redis_password.txt
chmod 600 infra/secrets/keys/redis_password.txt
```

#### Wrong Permissions

```bash
# Verification shows:
[WARNING] keys/postgres_password.txt: Permissions should be 600 (current: 644)
```

**Solution**:
```bash
# Run verify again (auto-fixes permissions)
./infra/secrets/generate_secrets.sh --verify

# Or fix manually
chmod 600 infra/secrets/keys/*.txt
```

#### Certificate Validation Errors

```bash
# Check certificate chain
openssl crl2pkcs7 -nocrl -certfile infra/secrets/certs/postgres/server-chain.crt | \
  openssl pkcs7 -print_certs -noout

# Verify certificate against CA
openssl verify -CAfile infra/secrets/certs/root-ca.crt \
  -untrusted infra/secrets/certs/intermediate-ca.crt \
  infra/secrets/certs/postgres/server.crt
```

#### Docker Secrets Not Found

```bash
# Check file paths in docker-compose.yml
ls -la infra/secrets/keys/postgres_password.txt
ls -la infra/secrets/certs/postgres/server.crt

# Verify Docker Compose syntax
docker-compose config
```

#### TLS Handshake Failures

**1. Check certificate expiration**:
```bash
openssl x509 -in infra/secrets/certs/postgres/server.crt -noout -dates
```

**2. Verify SANs match hostname**:
```bash
openssl x509 -in infra/secrets/certs/postgres/server.crt -noout -ext subjectAltName
```

**3. Test TLS connection**:
```bash
openssl s_client -connect postgres:5432 -starttls postgres
```

#### Serial Number File Issues

```bash
# Check serial number file contents
cat infra/secrets/certs/root-ca.srl
cat infra/secrets/certs/intermediate-ca.srl

# ⚠️ Missing serial files (DANGER: May cause serial collisions)
# If .srl files are accidentally deleted, you can recreate them:
echo "1000000000000001" > infra/secrets/certs/root-ca.srl
echo "1000000000000001" > infra/secrets/certs/intermediate-ca.srl
# ⚠️ WARNING: Only do this if you're certain no certificates exist with those serials

# Corrupted serial files
# Restore from backup or increment to a safe value:
echo "$(printf '%040X' $((0x$(cat infra/secrets/certs/root-ca.srl) + 100)))" > infra/secrets/certs/root-ca.srl
```

### Regeneration Scenarios

#### Compromised Secrets

```bash
# Backup existing secrets
./infra/secrets/generate_secrets.sh --backup-only

# Force regenerate all secrets
./infra/secrets/generate_secrets.sh --force --generate-pki --force-ca

# Restart services
docker-compose down && docker-compose up -d
```

#### Certificate Expiration

```bash
# Check expiration dates
./infra/secrets/generate_secrets.sh --verify

# Regenerate service certificates only (preserves CA)
./infra/secrets/generate_secrets.sh --generate-pki

# Restart affected services
docker-compose restart postgres redis temporal
```

#### CA Certificate Compromise

```bash
# ⚠️ WARNING: This invalidates all existing certificates!
./infra/secrets/generate_secrets.sh --generate-pki --force-ca

# All services must be restarted
docker-compose down && docker-compose up -d
```

### Monitoring and Maintenance

#### Regular Tasks

**1. Weekly: Verify secret integrity**
```bash
./infra/secrets/generate_secrets.sh --verify
```

**2. Monthly: Check certificate expiration**
```bash
find infra/secrets/certs -name "*.crt" -exec openssl x509 -in {} -noout -subject -dates \;
```

**3. Annually: Rotate service certificates**
```bash
./infra/secrets/generate_secrets.sh --generate-pki
```

**4. Every 5 years: Plan intermediate CA renewal**

**5. Every 10 years: Plan root CA renewal**

#### Backup Verification

```bash
# Test backup restoration
cp -r infra/secrets/backup_YYYYMMDD_HHMMSS/* infra/secrets/
./infra/secrets/generate_secrets.sh --verify
```

## Related Documentation

- [Security Overview](../security.md) - Application security architecture
- [Configuration Guide](../configuration.md) - Configuration management
- [Production Deployment](../PRODUCTION_DEPLOYMENT.md) - Full production deployment guide
- [Redis Security](../redis/security.md) - Redis-specific security configuration
- [PostgreSQL Security](../postgres/security.md) - Database security and TLS setup
- [Temporal Security](../temporal/security.md) - Temporal mTLS configuration

## Summary

The `infra/secrets/generate_secrets.sh` script provides:

✅ **Centralized Management**: All secrets and certificates in one tool  
✅ **Cryptographic Security**: Uses OpenSSL and `/dev/urandom` for entropy  
✅ **Automatic Backup**: Preserves existing secrets before changes  
✅ **Complete PKI**: Full certificate hierarchy with comprehensive SANs  
✅ **Easy Verification**: Built-in validation and listing tools  
✅ **Production Ready**: Proper permissions, industry best practices  
✅ **Docker Integration**: Native secrets support for all environments  
✅ **Flexible Deployment**: Supports Docker, Kubernetes, and cloud platforms

**Quick Reference**:
```bash
# Generate all secrets and certificates
./infra/secrets/generate_secrets.sh --generate-pki

# Verify everything is correct
./infra/secrets/generate_secrets.sh --verify

# List all generated files
./infra/secrets/generate_secrets.sh --list

# Create manual backup before changes
./infra/secrets/generate_secrets.sh --backup-only
```

**Remember**:
- 🔒 Never commit secrets to version control
- 🔄 Rotate secrets every 90 days
- 📝 Document any manual changes
- ✅ Verify after generation or restoration
- 💾 Keep backups in secure location
- 🔐 Include `.srl` files in CA backups
