#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-api-forge-prod}"

echo "Creating/updating secrets in namespace: ${NAMESPACE}"

# Create namespace if it doesn't exist
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

kubectl -n "$NAMESPACE" delete secret postgres-secrets postgres-tls postgres-ca redis-secrets app-secrets >/dev/null 2>&1 || true

# Ensure secrets exist
if [ ! -f infra/secrets/keys/postgres_password.txt ]; then
    echo "Error: infra/secrets/keys/postgres_password.txt not found."
    exit 1
fi

kubectl -n "$NAMESPACE" create secret generic postgres-secrets \
  --from-file=postgres_password=infra/secrets/keys/postgres_password.txt \
  --from-file=postgres_app_user_pw=infra/secrets/keys/postgres_app_user_pw.txt \
  --from-literal=temporal_user=temporaluser \
  --from-file=temporal_password=infra/secrets/keys/postgres_temporal_pw.txt

kubectl -n "$NAMESPACE" create secret generic postgres-tls \
  --from-file=tls.crt=infra/secrets/certs/postgres/server.crt \
  --from-file=tls.key=infra/secrets/certs/postgres/server.key

kubectl -n "$NAMESPACE" create secret generic postgres-ca \
  --from-file=ca.crt=infra/secrets/certs/root-ca.crt

kubectl -n "$NAMESPACE" create secret generic redis-secrets \
  --from-file=redis_password=infra/secrets/keys/redis_password.txt

kubectl -n "$NAMESPACE" create secret generic app-secrets \
  --from-file=session_signing_secret=infra/secrets/keys/session_signing_secret.txt \
  --from-file=csrf_signing_secret=infra/secrets/keys/csrf_signing_secret.txt \
  --from-file=oidc_keycloak_client_secret=infra/secrets/keys/oidc_keycloak_client_secret.txt \
  --from-file=oidc_google_client_secret=infra/secrets/keys/oidc_google_client_secret.txt \
  --from-file=oidc_microsoft_client_secret=infra/secrets/keys/oidc_microsoft_client_secret.txt

echo "Secrets created."
