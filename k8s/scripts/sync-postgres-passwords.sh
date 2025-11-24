#!/bin/bash
# Synchronize Postgres role passwords with the latest Kubernetes secrets
# Usage: ./sync-postgres-passwords.sh [namespace]

set -euo pipefail

NAMESPACE="${1:-api-forge-prod}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

ensure_prereqs() {
    if ! command -v kubectl >/dev/null 2>&1; then
        log_error "kubectl is not installed"
        exit 1
    fi

    if ! kubectl cluster-info >/dev/null 2>&1; then
        log_error "Unable to communicate with Kubernetes cluster"
        exit 1
    fi
}

find_postgres_pod() {
    kubectl get pods \
        -n "${NAMESPACE}" \
        -l app.kubernetes.io/name=postgres \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
}

run_sync() {
    local pod_name="$1"

    if [ -z "${pod_name}" ]; then
        log_warn "No postgres pod found in namespace ${NAMESPACE}; skipping password sync"
        return 0
    fi

    log_info "Waiting for postgres pod ${pod_name} to be ready..."
    if ! kubectl wait --for=condition=ready "pod/${pod_name}" -n "${NAMESPACE}" --timeout=180s >/dev/null 2>&1; then
        log_error "Postgres pod ${pod_name} failed to become ready"
        kubectl describe pod "${pod_name}" -n "${NAMESPACE}" || true
        exit 1
    fi

    log_info "Running sync-passwords.sh inside ${pod_name}..."

    local sync_wrapper
    sync_wrapper=$(cat <<'EOF'
set -euo pipefail
export PREFER_SECRET_FILES=true

if command -v gosu >/dev/null 2>&1; then
    exec gosu postgres /opt/entry/admin-scripts/sync-passwords.sh
elif command -v su >/dev/null 2>&1; then
    exec su - postgres -c "/opt/entry/admin-scripts/sync-passwords.sh"
else
    echo "[sync-passwords-wrapper] WARN: gosu/su not available; running as $(id -un)" >&2
    exec /opt/entry/admin-scripts/sync-passwords.sh
fi
EOF
)

    kubectl exec -n "${NAMESPACE}" "${pod_name}" -- bash -c "${sync_wrapper}"

    log_info "Password synchronization completed successfully"
}

main() {
    log_info "Synchronizing Postgres passwords in namespace: ${NAMESPACE}"
    ensure_prereqs
    POD_NAME="$(find_postgres_pod)"
    run_sync "${POD_NAME}"
    log_info "Done"
}

main "$@"
