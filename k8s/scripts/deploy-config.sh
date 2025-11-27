#!/bin/bash
set -e

################################################################################
# deploy-config.sh
# 
# Syncs configuration from source files and deploys to Kubernetes
# 
# What it does:
# 1. Copies config files from source locations to k8s/base/:
#    - .env → .env.k8s
#    - config.yaml → config.yaml.k8s
#    - infra/docker/prod/postgres/* → *.k8s files
# 2. Kustomize reads the copied files and auto-generates ConfigMaps
# 3. Deploys all resources to Kubernetes
# 4. Optionally restarts the app to pick up config changes
#
# Usage:
#   ./k8s/scripts/deploy-config.sh [--restart] [--sync-only]
#
# Options:
#   --restart     Also restart the app deployment after updating ConfigMap
#   --sync-only   Only sync config files, don't deploy
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
K8S_DIR="$PROJECT_ROOT/k8s"
K8S_BASE="$K8S_DIR/base"
K8S_SOURCES="$K8S_BASE/.k8s-sources"
CONFIGMAPS_DIR="$K8S_BASE/configmaps"
ENV_FILE="$PROJECT_ROOT/.env"

RESTART_APP=false
SYNC_ONLY=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --restart)
      RESTART_APP=true
      shift
      ;;
    --sync-only)
      SYNC_ONLY=true
      shift
      ;;
    --help)
      head -n 21 "$0" | tail -n +3
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Run with --help for usage"
      exit 1
      ;;
  esac
done

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "==========================================="
echo "  Kubernetes Configuration Sync & Deploy"
echo "==========================================="
echo ""

# ============================================================================
# STEP 1: Copy config files to k8s/base/.k8s-sources/
# ============================================================================
echo -e "${YELLOW}Step 1: Copying config files to k8s/base/.k8s-sources/${NC}"
echo "-------------------------------------------"

# Create .k8s-sources directory
mkdir -p "$K8S_SOURCES"

# .env file
if [[ ! -f "$ENV_FILE" ]]; then
  echo -e "${RED}✗ Error: .env file not found at: $ENV_FILE${NC}"
  echo ""
  echo "Create it from .env.example:"
  echo "  cp .env.example .env"
  echo "  vim .env"
  exit 1
fi
echo -n "  .env → .k8s-sources/.env.k8s (K8s-optimized)... "
cp "$ENV_FILE" "$K8S_SOURCES/.env.k8s"

# Kubernetes-specific overrides: Force production environment
# In K8s, we always want production mode (uses service discovery: postgres:5432, redis:6379, temporal:7233)
# Development mode would try to connect to localhost URLs which don't work in K8s
sed -i 's/^APP_ENVIRONMENT=.*/APP_ENVIRONMENT=production/' "$K8S_SOURCES/.env.k8s"

echo -e "${GREEN}✓${NC}"

# config.yaml
CONFIG_FILE="$PROJECT_ROOT/config.yaml"
if [[ ! -f "$CONFIG_FILE" ]]; then
  echo -e "${RED}✗ Error: config.yaml not found${NC}"
  exit 1
fi
echo -n "  config.yaml → .k8s-sources/config.yaml.k8s... "
cp "$CONFIG_FILE" "$K8S_SOURCES/config.yaml.k8s"
echo -e "${GREEN}✓${NC}"

# PostgreSQL configs
PG_DIR="$PROJECT_ROOT/infra/docker/prod/postgres"
PG_INIT_DIR="$PG_DIR/init-scripts"

if [[ ! -d "$PG_DIR" ]]; then
  echo -e "${RED}✗ Error: PostgreSQL config directory not found${NC}"
  exit 1
fi

echo -n "  postgresql.conf → .k8s-sources/postgresql.conf.k8s... "
cp "$PG_DIR/postgresql.conf" "$K8S_SOURCES/postgresql.conf.k8s"
echo -e "${GREEN}✓${NC}"

echo -n "  pg_hba.conf → .k8s-sources/pg_hba.conf.k8s (K8s-optimized)... "
cp "$PG_DIR/pg_hba.conf" "$K8S_SOURCES/pg_hba.conf.k8s"

# Kubernetes-specific modification: Replace CIDR-based rules with 0.0.0.0/0
# Security is enforced via NetworkPolicy instead of IP restrictions
# This makes the config portable across any K8s cluster
sed -i 's|^hostssl  all            all             172\.30\.50\.0/24|# hostssl  all            all             172.30.50.0/24  # Disabled for K8s - using NetworkPolicy|' "$K8S_SOURCES/pg_hba.conf.k8s"
sed -i 's|^hostssl  all            all             172\.18\.0\.0/16|# hostssl  all            all             172.18.0.0/16   # Disabled for K8s - using NetworkPolicy|' "$K8S_SOURCES/pg_hba.conf.k8s"
sed -i 's|^hostssl  all            all             10\.10\.0\.0/16|# hostssl  all            all             10.10.0.0/16    # Disabled for K8s - using NetworkPolicy|' "$K8S_SOURCES/pg_hba.conf.k8s"
sed -i 's|^hostssl  all            all             10\.244\.0\.0/16|# hostssl  all            all             10.244.0.0/16   # Disabled for K8s - using NetworkPolicy|' "$K8S_SOURCES/pg_hba.conf.k8s"

# Add Kubernetes-friendly rule (allow SSL from any IP - NetworkPolicy controls access)
sed -i '/# 2) Allow TLS from your Docker\/LAN subnets only/a # Kubernetes: Allow SSL from any IP (NetworkPolicy enforces pod-level access control)\nhostssl  all            all             0.0.0.0/0               scram-sha-256   # K8s pods (secured via NetworkPolicy)' "$K8S_SOURCES/pg_hba.conf.k8s"

echo -e "${GREEN}✓${NC}"

echo -n "  01-init-app.sh → .k8s-sources/01-init-app.sh.k8s... "
cp "$PG_INIT_DIR/01-init-app.sh" "$K8S_SOURCES/01-init-app.sh.k8s"
echo -e "${GREEN}✓${NC}"

# PostgreSQL verifier
VERIFY_SCRIPT="$PG_DIR/verify-init.sh"
if [[ -f "$VERIFY_SCRIPT" ]]; then
  echo -n "  verify-init.sh → .k8s-sources/verify-init.sh.k8s (K8s-optimized)... "
  cp "$VERIFY_SCRIPT" "$K8S_SOURCES/verify-init.sh.k8s"
  
  # Kubernetes-specific modification: Update ALLOWED_SUBNETS to match NetworkPolicy approach
  # In K8s, we allow 0.0.0.0/0 in pg_hba.conf and use NetworkPolicy for pod-level access control
  sed -i 's|^ALLOWED_SUBNETS="${ALLOWED_SUBNETS:-172.30.50.0/24}"|ALLOWED_SUBNETS="${ALLOWED_SUBNETS:-0.0.0.0/0}"  # K8s: allow all IPs, NetworkPolicy controls access|' "$K8S_SOURCES/verify-init.sh.k8s"
  
  echo -e "${GREEN}✓${NC}"
else
  echo -e "${YELLOW}⚠ Warning: verify-init.sh not found, skipping${NC}"
fi

# Universal entrypoint script
UNIVERSAL_ENTRYPOINT="$PROJECT_ROOT/infra/docker/prod/scripts/universal-entrypoint.sh"

if [[ -f "$UNIVERSAL_ENTRYPOINT" ]]; then
  echo -n "  universal-entrypoint.sh → .k8s-sources/universal-entrypoint.sh.k8s... "
  cp "$UNIVERSAL_ENTRYPOINT" "$K8S_SOURCES/universal-entrypoint.sh.k8s"
  echo -e "${GREEN}✓${NC}"
else
  echo -e "${RED}✗ Error: universal-entrypoint.sh not found${NC}"
  exit 1
fi

# Temporal scripts
TEMPORAL_DIR="$PROJECT_ROOT/infra/docker/prod/temporal/scripts"

if [[ ! -d "$TEMPORAL_DIR" ]]; then
  echo -e "${RED}✗ Error: Temporal scripts directory not found${NC}"
  exit 1
fi

echo -n "  schema-setup.sh → .k8s-sources/temporal-schema-setup.sh.k8s... "
cp "$TEMPORAL_DIR/schema-setup.sh" "$K8S_SOURCES/temporal-schema-setup.sh.k8s"
echo -e "${GREEN}✓${NC}"

echo -n "  entrypoint.sh → .k8s-sources/temporal-entrypoint.sh.k8s... "
cp "$TEMPORAL_DIR/entrypoint.sh" "$K8S_SOURCES/temporal-entrypoint.sh.k8s"
echo -e "${GREEN}✓${NC}"

echo ""
echo -e "${GREEN}✓ All config files copied${NC}"

# Exit early if --sync-only flag was used
if [[ "$SYNC_ONLY" == "true" ]]; then
  echo ""
  echo "Sync complete! (--sync-only mode, not deploying)"
  echo ""
  echo "To deploy, run:"
  echo "  ./k8s/scripts/deploy-config.sh"
  exit 0
fi

# ============================================================================
# STEP 2: Validate Kustomize Configuration
# ============================================================================
echo ""
echo -e "${YELLOW}Step 2: Validating Kustomize${NC}"
echo "-------------------------------------------"

echo -n "  Testing kustomize build... "
if kubectl kustomize "$K8S_BASE" > /dev/null 2>&1; then
  echo -e "${GREEN}✓${NC}"
else
  echo -e "${RED}✗${NC}"
  echo ""
  echo "Kustomize build failed. Run this to see errors:"
  echo "  kubectl kustomize k8s/base/"
  exit 1
fi

# ============================================================================
# STEP 3: Preview Changes
# ============================================================================
echo ""
echo -e "${YELLOW}Step 3: Preview ConfigMaps${NC}"
echo "-------------------------------------------"
echo "Environment variables (first 10):"
kubectl kustomize "$K8S_BASE" | grep -A 50 "kind: ConfigMap" | grep -A 50 "name: app-env" | grep "  [A-Z]" | head -10
echo "  ..."
echo ""

# ============================================================================
# STEP 4: Deploy to Kubernetes
# ============================================================================
echo ""
echo -e "${YELLOW}Step 4: Deploy to Kubernetes${NC}"
echo "-------------------------------------------"

read -p "Deploy to Kubernetes? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelled."
  exit 0
fi

echo ""
echo "Deploying..."
kubectl apply -k "$K8S_BASE"

echo ""
echo -e "${GREEN}✓ Deployment complete${NC}"

# Restart app if requested
if [[ "$RESTART_APP" == "true" ]]; then
  echo ""
  echo "Restarting app deployment..."
  kubectl rollout restart deployment/app -n api-forge-prod
  echo -e "${GREEN}✓ App restarting${NC}"
fi

echo ""
echo "==========================================="
echo "  ✓ Configuration Deployed Successfully"
echo "==========================================="
echo ""
echo "Files copied to k8s/base/ and ConfigMaps auto-generated:"
echo "  • .env → .env.k8s → app-env ConfigMap"
echo "  • config.yaml → config.yaml.k8s → app-config ConfigMap"
echo "  • postgresql.conf → postgresql.conf.k8s → postgres-config ConfigMap"
echo "  • pg_hba.conf → pg_hba.conf.k8s → postgres-config ConfigMap"
echo "  • 01-init-app.sh → 01-init-app.sh.k8s → postgres-config ConfigMap"
echo "  • verify-init.sh → verify-init.sh.k8s → postgres-verifier-config ConfigMap"
echo ""
echo "Next time you change config:"
echo "  1. Edit source files (.env, config.yaml, etc.)"
echo "  2. Run: ./k8s/scripts/deploy-config.sh --restart"
echo ""
echo "Or to just copy files without deploying:"
echo "  ./k8s/scripts/deploy-config.sh --sync-only"
echo "==========================================="
