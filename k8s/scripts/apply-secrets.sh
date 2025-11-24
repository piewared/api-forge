#!/bin/bash
# Kubernetes Secret Application Script
# This script pushes generated secrets from infra/secrets into Kubernetes
# Usage: ./apply-secrets.sh [namespace]

set -euo pipefail

# Configuration
NAMESPACE="${1:-api-forge-prod}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SECRETS_DIR="${PROJECT_ROOT}/infra/secrets"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed"
        exit 1
    fi
    
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    
    if [ ! -d "${SECRETS_DIR}" ]; then
        log_error "Secrets directory not found: ${SECRETS_DIR}"
        exit 1
    fi
    
    log_info "Prerequisites check passed"
}

create_namespace() {
    log_info "Creating namespace: ${NAMESPACE}"
    
    if kubectl get namespace "${NAMESPACE}" &> /dev/null; then
        log_warn "Namespace ${NAMESPACE} already exists"
    else
        # Use kubectl apply instead of create to be consistent with declarative approach
        # This ensures the namespace has the proper annotations for later kubectl apply operations
        kubectl apply -f - <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: ${NAMESPACE}
  labels:
    app.kubernetes.io/name: api-forge
    app.kubernetes.io/instance: production
EOF
        log_info "Namespace ${NAMESPACE} created"
    fi
}

delete_existing_secrets() {
    log_warn "Deleting existing secrets in namespace ${NAMESPACE}..."
    
    kubectl delete secret postgres-secrets -n "${NAMESPACE}" --ignore-not-found=true
    kubectl delete secret redis-secrets -n "${NAMESPACE}" --ignore-not-found=true
    kubectl delete secret app-secrets -n "${NAMESPACE}" --ignore-not-found=true
    kubectl delete secret postgres-tls -n "${NAMESPACE}" --ignore-not-found=true
    kubectl delete secret postgres-ca -n "${NAMESPACE}" --ignore-not-found=true
    
    log_info "Existing secrets deleted"
}

create_postgres_secrets() {
    log_info "Creating PostgreSQL secrets..."
    
    local keys_dir="${SECRETS_DIR}/keys"
    
    # Check if required files exist
    local required_files=(
        "postgres_password.txt"
        "postgres_app_owner_pw.txt"
        "postgres_app_user_pw.txt"
        "postgres_app_ro_pw.txt"
        "postgres_temporal_pw.txt"
    )
    
    for file in "${required_files[@]}"; do
        if [ ! -f "${keys_dir}/${file}" ]; then
            log_error "Required secret file not found: ${keys_dir}/${file}"
            exit 1
        fi
    done
    
    kubectl create secret generic postgres-secrets \
        --from-file=postgres_password="${keys_dir}/postgres_password.txt" \
        --from-file=postgres_app_owner_pw="${keys_dir}/postgres_app_owner_pw.txt" \
        --from-file=postgres_app_user_pw="${keys_dir}/postgres_app_user_pw.txt" \
        --from-file=postgres_app_ro_pw="${keys_dir}/postgres_app_ro_pw.txt" \
        --from-file=postgres_temporal_pw="${keys_dir}/postgres_temporal_pw.txt" \
        --namespace="${NAMESPACE}"
    
    log_info "PostgreSQL secrets created successfully"
}

create_postgres_tls_secrets() {
    log_info "Creating PostgreSQL TLS secrets..."
    
    local certs_dir="${SECRETS_DIR}/certs/postgres"
    
    # Check if required files exist
    if [ ! -f "${certs_dir}/server.crt" ] || [ ! -f "${certs_dir}/server.key" ]; then
        log_error "PostgreSQL TLS certificate files not found in ${certs_dir}"
        exit 1
    fi
    
    kubectl create secret generic postgres-tls \
        --from-file=server.crt="${certs_dir}/server-chain.crt" \
        --from-file=server.key="${certs_dir}/server.key" \
        --namespace="${NAMESPACE}"
    
    log_info "PostgreSQL TLS secrets created successfully"
}

create_postgres_ca_secret() {
    log_info "Creating PostgreSQL CA certificate secret..."
    
    local certs_dir="${SECRETS_DIR}/certs"
    
    if [ ! -f "${certs_dir}/ca-bundle.crt" ]; then
        log_error "CA bundle not found: ${certs_dir}/ca-bundle.crt"
        exit 1
    fi

    if [ ! -f "${certs_dir}/root-ca.crt" ]; then
        log_error "Root CA not found: ${certs_dir}/root-ca.crt"
        exit 1
    fi

    if [ ! -f "${certs_dir}/intermediate-ca.crt" ]; then
        log_error "Intermediate CA not found: ${certs_dir}/intermediate-ca.crt"
        exit 1
    fi
    
    kubectl create secret generic postgres-ca \
        --from-file=ca-bundle.crt="${certs_dir}/ca-bundle.crt" \
        --from-file=root-ca.crt="${certs_dir}/root-ca.crt" \
        --from-file=intermediate-ca.crt="${certs_dir}/intermediate-ca.crt" \
        --namespace="${NAMESPACE}"
    
    log_info "PostgreSQL CA secret created successfully"
}

create_redis_secrets() {
    log_info "Creating Redis secrets..."
    
    local keys_dir="${SECRETS_DIR}/keys"
    
    if [ ! -f "${keys_dir}/redis_password.txt" ]; then
        log_error "Redis password file not found: ${keys_dir}/redis_password.txt"
        exit 1
    fi
    
    kubectl create secret generic redis-secrets \
        --from-file=redis_password="${keys_dir}/redis_password.txt" \
        --namespace="${NAMESPACE}"
    
    log_info "Redis secrets created successfully"
}

create_app_secrets() {
    log_info "Creating application secrets..."
    
    local keys_dir="${SECRETS_DIR}/keys"
    
    # Check if required files exist
    local required_files=(
        "session_signing_secret.txt"
        "csrf_signing_secret.txt"
        "oidc_google_client_secret.txt"
        "oidc_microsoft_client_secret.txt"
        "oidc_keycloak_client_secret.txt"
    )
    
    for file in "${required_files[@]}"; do
        if [ ! -f "${keys_dir}/${file}" ]; then
            log_error "Required secret file not found: ${keys_dir}/${file}"
            exit 1
        fi
    done

    kubectl create secret generic app-secrets \
        --from-file=session_signing_secret="${keys_dir}/session_signing_secret.txt" \
        --from-file=csrf_signing_secret="${keys_dir}/csrf_signing_secret.txt" \
        --from-file=oidc_google_client_secret="${keys_dir}/oidc_google_client_secret.txt" \
        --from-file=oidc_microsoft_client_secret="${keys_dir}/oidc_microsoft_client_secret.txt" \
        --from-file=oidc_keycloak_client_secret="${keys_dir}/oidc_keycloak_client_secret.txt" \
        --namespace="${NAMESPACE}"
    
    log_info "Application secrets created successfully"
}

verify_secrets() {
    log_info "Verifying created secrets..."
    
    local secrets=(
        "postgres-secrets"
        "postgres-tls"
        "postgres-ca"
        "redis-secrets"
        "app-secrets"
    )
    
    local all_exist=true
    for secret in "${secrets[@]}"; do
        if kubectl get secret "${secret}" -n "${NAMESPACE}" &> /dev/null; then
            log_info "✓ Secret '${secret}' exists"
        else
            log_error "✗ Secret '${secret}' not found"
            all_exist=false
        fi
    done
    
    if [ "${all_exist}" = true ]; then
        log_info "All secrets verified successfully"
    else
        log_error "Some secrets are missing"
        exit 1
    fi
}

main() {
    log_info "Starting Kubernetes secret creation for namespace: ${NAMESPACE}"
    log_info "Project root: ${PROJECT_ROOT}"
    log_info "Secrets directory: ${SECRETS_DIR}"
    echo ""
    
    check_prerequisites
    create_namespace
    delete_existing_secrets
    
    echo ""
    create_postgres_secrets
    create_postgres_tls_secrets
    create_postgres_ca_secret
    create_redis_secrets
    create_app_secrets
    
    echo ""
    verify_secrets
    
    echo ""
    log_info "✓ Secret application completed successfully!"
    log_info "You can now deploy the application using: kubectl apply -k k8s/base/"
}

# Run main function
main
