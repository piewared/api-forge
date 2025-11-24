# Kubernetes Configuration: Simple Guide

## Overview

Your Kubernetes configuration is automatically generated from your `.env` file. No manual YAML editing needed.

## How It Works

```
Source files  →  copy to k8s/base/.k8s-sources/  →  Kustomize  →  ConfigMaps  →  Your app
```

1. You edit source files (`.env`, `config.yaml`, postgres configs, etc.)
2. The deploy script copies all source files to `k8s/base/.k8s-sources/` with `.k8s` extension
3. Kustomize reads the `.k8s` files and auto-generates ConfigMaps
4. Your app gets the config as environment variables or mounted files

**Why copy files?** Kustomize security requires files to be in the `k8s/base/` directory. We copy source files to `.k8s-sources/` subdirectory with `.k8s` extension. This directory is gitignored.

## Setup (Already Done)

The `k8s/base/kustomization.yaml` file uses `configMapGenerator` to auto-generate all ConfigMaps:

```yaml
configMapGenerator:
  # Environment variables (from .env file)
  - name: app-env
    envs:
      - .k8s-sources/.env.k8s
  
  # Application config (from config.yaml)
  - name: app-config
    files:
      - config.yaml=.k8s-sources/config.yaml.k8s
  
  # PostgreSQL configs
  - name: postgres-config
    files:
      - postgresql.conf=.k8s-sources/postgresql.conf.k8s
      - pg_hba.conf=.k8s-sources/pg_hba.conf.k8s
      - 01-init-app.sh=.k8s-sources/01-init-app.sh.k8s
  
  # PostgreSQL verifier
  - name: postgres-verifier-config
    files:
      - verify-postgres.sh=.k8s-sources/verify-postgres.sh.k8s
  
  # Temporal scripts
  - name: temporal-config
    files:
      - schema-setup.sh=.k8s-sources/temporal-schema-setup.sh.k8s
      - entrypoint.sh=.k8s-sources/temporal-entrypoint.sh.k8s
```

**Note**: Operational values like `TZ`, `LOG_FORMAT`, and `LOG_LEVEL` are hardcoded directly in deployment manifests (not in ConfigMaps) for consistency.

**Consistent Pattern:** All config files follow the same workflow:
1. Edit source file
2. Run `deploy-config.sh` (copies to k8s/base/.k8s-sources/)
3. Kustomize auto-generates ConfigMaps
4. Deploy to Kubernetes

## Daily Workflow

### Change configuration

```bash
vim .env
```

### Deploy changes

```bash
./k8s/scripts/deploy-config.sh --restart
```

That's it! The script:
- Validates your `.env` file
- Generates the ConfigMap from `.env`
- Deploys to Kubernetes
- Restarts your app to pick up changes

## Manual Deployment

If you prefer to run commands directly:

```bash
# Deploy (ConfigMap auto-generated from .env)
kubectl apply -k k8s/base/

# Restart app to pick up config changes
kubectl rollout restart deployment/app -n api-forge-prod
```

## What Goes in .env

**Non-sensitive configuration only:**
- Database URLs (without passwords)
- Redis URLs (without passwords)
- Feature flags
- API endpoints
- Port numbers
- Environment name (development/production)

**NOT secrets:**
- Passwords → Use Kubernetes Secrets
- API keys → Use Kubernetes Secrets
- Tokens → Use Kubernetes Secrets
- Certificates → Use Kubernetes Secrets

## Environment-Specific Values

Your `.env` file should use the `PRODUCTION_*` and `DEVELOPMENT_*` pattern:

```bash
APP_ENVIRONMENT=production

DEVELOPMENT_DATABASE_URL=postgresql://user@localhost:5433/db
PRODUCTION_DATABASE_URL=postgresql://user@postgres:5432/db

DEVELOPMENT_REDIS_URL=redis://localhost:6380
PRODUCTION_REDIS_URL=redis://redis:6379
```

Your app's `config.yaml` decides which to use based on `APP_ENVIRONMENT`.

## Troubleshooting

### Rotating Postgres passwords / secrets

When you regenerate secrets (for example by re-running `infra/secrets/generate_secrets.sh` or rotating files under `infra/secrets/keys`), the Kubernetes `Secret` objects get recreated by `k8s/scripts/apply-secrets.sh`. The mounted files inside the Postgres pod update automatically, but the database roles still keep their previous passwords until you run the `sync-passwords` helper.

- **CLI users:** `uv run api-forge-cli deploy k8s` now runs the sync step automatically after secrets are applied.
- **Manual users:** run `./k8s/scripts/sync-postgres-passwords.sh <namespace>` (defaults to `api-forge-prod`). The script waits for the running Postgres pod and executes `/opt/entry/admin-scripts/sync-passwords.sh` inside it so all roles (`app`, `readonly`, and `temporal`) align with the latest secrets.

If the script cannot find a Postgres pod it simply logs a warning and exits, which is expected on the very first deploy. For rotations, ensure the pod is running before invoking the script.

### ConfigMap not updating

The ConfigMap only updates when you run `kubectl apply -k k8s/base/`. Changes to `.env` don't automatically deploy.

**Solution:** Run the deploy script or `kubectl apply -k k8s/base/`

### App not picking up new config

Your app reads config at startup. It won't see changes until it restarts.

**Solution:** Add `--restart` flag to the deploy script, or manually:
```bash
kubectl rollout restart deployment/app -n api-forge-prod
```

### "unable to find file .k8s-sources/.env.k8s"

The deploy script failed to copy `.env` to `k8s/base/.k8s-sources/.env.k8s`.

**Solution:** 
```bash
# Make sure .env exists
cp .env.example .env
vim .env  # Add real values

# Run deploy script (it will copy .env to k8s/base/.k8s-sources/)
./k8s/scripts/deploy-config.sh
```

## Advanced: Preview Without Deploying

```bash
# See what would be generated
kubectl kustomize k8s/base/ | less

# See just the ConfigMap
kubectl kustomize k8s/base/ | grep -A 100 "kind: ConfigMap"
```

## Files You Care About

**Source Files (edit these):**
```
.env                                           # Environment variables
config.yaml                                    # Application configuration
infra/docker/prod/postgres/postgresql.conf     # PostgreSQL server config
infra/docker/prod/postgres/pg_hba.conf         # PostgreSQL auth rules
infra/docker/prod/postgres/init-scripts/*.sh   # Database init scripts
infra/docker/prod/postgres/verify-init.sh      # Database verifier
infra/docker/prod/temporal/scripts/*.sh        # Temporal setup scripts
```

**Auto-Generated (don't edit):**
```
k8s/base/.k8s-sources/         # Copies of source files (gitignored directory)
k8s/base/kustomization.yaml    # Kustomize config (defines configMapGenerator)
k8s/scripts/deploy-config.sh   # Deployment script
```

## Summary

**What you do:**
1. Edit source files (`.env`, `config.yaml`, postgres configs, etc.)
2. Run `./k8s/scripts/deploy-config.sh --restart`

**What happens automatically:**
1. Script copies all source files to `k8s/base/.k8s-sources/`
2. Kustomize reads the `.k8s` files from `.k8s-sources/`
3. Auto-generates all ConfigMaps (app-env, app-config, postgres-config, postgres-verifier-config, temporal-config)
4. Deploys to Kubernetes
5. App restarts with new config

**Consistent workflow for all configs. No manual YAML editing. Single source of truth.**
