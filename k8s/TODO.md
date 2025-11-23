# Kubernetes Deployment Assessment

_Date: 2025-11-20_

## ✅ Strengths

- Kustomize-driven layout keeps manifests organized (`k8s/base/*`) with well-documented helper scripts.
- Consistent labels, probes, resource requests/limits, `enableServiceLinks: false`, and seccomp profiles across workloads.
- Secrets mounted as individual read-only files; PostgreSQL TLS enforced and validated via the `postgres-verifier` job.
- `deploy-resources.sh` sequences dependencies, waits for readiness, and surfaces logs when components misbehave.

## ⚠️ Risks, Gaps, and Footguns

### Secrets & Configuration
- `.env` is converted into the `app-env` **ConfigMap**, so secrets (OIDC client secrets, API keys, session keys) end up in plain text and are injected into every workload despite existing `app-secrets` resources.
- `create-secrets.sh` deletes all secrets before recreating them; a mid-run failure wipes credentials and crashes dependent pods.
- No rotation guidance—especially for TLS—nor automation to re-run `postgres-verifier` or other jobs after key changes.

### Workload Security
- `app` and `worker` containers start as root, add multiple capabilities, keep writable root filesystems, and rely on an entrypoint to drop privileges without enforcing `runAsNonRoot`/`runAsUser`.
- PostgreSQL/Redis also run as Deployments rather than StatefulSets with strict UID/GID settings and surge-safe rolling updates.

### Networking
- NetworkPolicies cover ingress only; egress is fully open and the “default deny” policy is commented out, so compromised pods can reach anything in-cluster.
- `app` and `temporal-web` policies allow traffic from `from: []`, which (without default deny) effectively allows all traffic and gives false confidence.
- `pg_hba.conf` is patched to `0.0.0.0/0`, defeating CIDR detection and widening blast radius.

### Stateful Services & Durability
- PostgreSQL/Redis Deployments lack StatefulSet guarantees (stable network IDs, ordered restarts); PodDisruptionBudgets are missing, so a drain can evict every critical pod.
- Backups rely solely on PVC survival; there are no CronJobs to dump databases or copy `app-logs` elsewhere.

### Automation UX
- `deploy-config.sh` can apply changes without diff/confirmation for the active namespace; accidental `y` presses propagate config.
- `deploy-resources.sh` re-applies everything blindly and, on immutable-field errors, deletes/recreates deployments—causing downtime.
- `detect-pod-cidr.sh` writes guesses into `.env`, but deployment later rewrites `pg_hba.conf` to `0.0.0.0/0`, so the workflow is confusing and ineffective.

### Observability & Resiliency
- No log shipping/metrics; API and worker share the same `app-logs` PVC, so concurrent writes can corrupt files and operators still must exec into pods.
- Temporal schema/namespace jobs only warn on failure; the deployment script continues even when the workflow backend is unusable.

## 🔧 Recommended Actions (Priority Order)

1. **Split secrets from config**: move sensitive `.env` entries into Kubernetes Secrets (possibly extend `app-secrets`) and keep ConfigMaps for non-sensitive settings only.
2. **Enable default deny + egress control**: turn on the commented default-deny ingress policy, add egress restrictions, and tighten `from: []` rules to actual ingress controller namespaces/IPs.
3. **Harden pods**: enforce `runAsUser`, `runAsGroup`, `runAsNonRoot`, drop unnecessary capabilities, and use read-only root filesystems with explicit writable `emptyDir`s.
4. **Convert data services to StatefulSets** and add PodDisruptionBudgets; document/automate backups via CronJobs.
5. **Make automation idempotent and safer**: have `create-secrets.sh` apply without deleting first, add diff/approval to `deploy-config.sh`, parameterize namespaces, and improve `deploy-resources.sh` handling of immutable fields.
6. **Pin images** to immutable tags/digests and prefer `imagePullPolicy: Always` (or digests) in production.
7. **Instrument observability**: add log/metric exporters and CronJobs to rerun `postgres-verifier` after TLS changes with alerts on failure.

## 📋 Quality Gates (Current State)

- Build: _not run_ (review only)
- Lint/Typecheck: _not run_
- Tests: _not run_

> Use this list as a living TODO for the Kubernetes posture. As items are addressed, capture evidence (e.g., PR links, test outputs) under each bullet.
