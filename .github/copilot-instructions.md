# Copilot Agent Onboarding - FastAPI Production Template

## ⚠️ CRITICAL INSTRUCTIONS FOR AI ASSISTANTS

**DO NOT create meta-documentation files** (e.g., DOCUMENTATION_CONSOLIDATION.md, DOCUMENTATION_VERIFICATION.md, CHANGES.md, etc.). These pollute the repository with information that is only relevant to the AI's work process, not to actual users or developers. 

**When making changes**:
- Edit existing documentation files directly
- Do not create summary files about what you changed
- Do not create verification reports
- Users care about the final state, not the change process

---

## Repository Overview

**Project Type**: Copier-based FastAPI API template for production-ready microservices  
**Primary Language**: Python 3.13+  
**Package Manager**: `uv` (fast Python package installer/manager)  
**Size**: ~500 files (infrastructure code plus some legacy template remnants)  
**Key Frameworks**: FastAPI, SQLModel, Pydantic, Temporal, Docker Compose

This repository hosts the primary infrastructure codebase inside `src/` along with the Copier template definition (`copier.yml` plus supporting scripts). Generated projects pull directly from this tree, so keep it production-grade.

### Core Features
- OIDC authentication (Keycloak dev/test, Google/Microsoft prod) with BFF pattern
- Secure session management with HttpOnly cookies, CSRF protection, client fingerprinting
- PostgreSQL (prod) / SQLite (dev) with SQLModel ORM
- Redis for caching, sessions, and rate limiting
- Temporal workflows for async/background processing
- Full Docker Compose development environment (Keycloak, PostgreSQL, Redis, Temporal)
- Clean Architecture with entities → repositories → services → API layers
- Hardened OIDC/JWT pipeline with nonce enforcement, configurable refresh-token policy, JWKS cache controls, and sanitized logging

---

## Critical Build & Test Commands

**ALWAYS use these exact command sequences. They have been validated to work.**

**CLI Entrypoint Reminder**: All repository automation flows run through the `api-forge-cli` Typer app. Always invoke it with `uv run api-forge-cli …` so the managed virtualenv is used.

### Environment Setup (First Time)
```bash
# 1. Copy environment file
cp .env.example .env

# 2. Install dependencies (uv handles virtual env automatically)
uv sync --dev

# 3. Start Docker development environment
uv run api-forge-cli dev start-env
# Wait 30-60 seconds for services to initialize

# 4. Verify services are healthy
uv run api-forge-cli dev status

# 5. Initialize database
uv run init-db
```

### Development Server
```bash
# Method 1: Using CLI (recommended, includes hot reload)
uv run api-forge-cli dev start-server

# Method 2: Direct uvicorn (infrastructure testing)
PYTHONPATH=src uv run uvicorn src.app.api.http.app:app --reload

```

### Testing
```bash
# Run all tests (328 tests, ~15-30 seconds)
uv run pytest tests/ -v

# Run specific test categories
uv run pytest tests/unit/ -v              # Unit tests only
uv run pytest tests/integration/ -v       # Integration tests

# With coverage
uv run pytest --cov=src --cov-report=xml

# Skip manual tests (require user interaction)
uv run pytest -m "not manual"
```

### Code Quality
```bash
# Lint (shows 36 errors currently - mostly formatting)
uv run ruff check src/

# Auto-fix linting issues (fixes 31/36 errors)
uv run ruff check src/ --fix

# Format code
uv run ruff format src/

# Type checking (strict mode enabled)
uv run mypy src/
```

### Docker Operations
```bash
# Start dev environment
uv run api-forge-cli dev start-env

# Check service status
uv run api-forge-cli dev status

# View logs for specific service
uv run api-forge-cli dev logs postgres
uv run api-forge-cli dev logs keycloak
uv run api-forge-cli dev logs redis
uv run api-forge-cli dev logs temporal

# Stop environment (preserves data)
uv run api-forge-cli dev stop-env

# Complete cleanup (destroys volumes/data)
docker-compose -f docker-compose.dev.yml down -v
```

### Database Management
```bash
# Initialize/reset database
uv run init-db

# Direct DB access (dev environment)
docker exec -it api-forge-postgres-dev psql -U postgres -d appdb
```

---

## Known Issues & Workarounds

### 1. CLI Status Command Container Names (FIXED)
**Issue**: `uv run api-forge-cli dev status` showed services as "Not running" when they were actually running  
**Root Cause**: Container name mismatch - code was checking for `app_dev_*` names but actual containers use `api-forge-*-dev` naming convention  
**Fix Applied**: Updated `src/dev/cli/dev_commands.py` to use correct container names:
- `api-forge-keycloak-dev`
- `api-forge-postgres-dev`
- `api-forge-redis-dev`
- `api-forge-temporal-dev`
- `api-forge-temporal-ui-dev`

### 2. Keycloak Setup Module Import Error (FIXED)
**Issue**: `ModuleNotFoundError: No module named 'src.dev.setup_keycloak'`  
**Fix Applied**: Volume mount path corrected from `../src/dev` to `./src/dev` in `docker-compose.dev.yml`  
**Action**: Rebuild keycloak-setup service if error persists

### 3. Temporal Database Connection Issues
**Issue**: Temporal server can't connect despite schemas existing  
**Root Cause**: `temporaluser` search_path is `"$user", public` but schemas are `temporal` and `temporal_visibility`  
**Workaround**: Grant schema access:
```sql
ALTER USER temporaluser SET search_path TO temporal,temporal_visibility,public;
GRANT USAGE ON SCHEMA temporal, temporal_visibility TO temporaluser;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA temporal TO temporaluser;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA temporal_visibility TO temporaluser;
```

### 4. Test Failures in Integration Tests
**Expected Behavior**: Some integration tests fail without Docker environment running  
**Action**: ALWAYS run `uv run api-forge-cli dev start-env` before integration tests

### 7. PostgreSQL TLS Certificate Verification (HELM DEPLOYMENT)
**Context**: The `postgres-verifier` Kubernetes job (deployed via Helm) mounts the `postgres-tls` secret and enforces certificate permissions before finishing.  
**Requirements**:
- Secret must contain `server.crt` (<= 0644) and `server.key` (<= 0600) files
- Helm template `infra/helm/api-forge/templates/jobs/postgres-verifier.yaml` mounts each file individually via `subPath`
- Run `uv run api-forge-cli deploy up k8s` (Helm deployment) after updating TLS assets
**Troubleshooting**: If the job reports `Cert files not mounted` or permission errors:
  1. Ensure secrets were created: `./infra/helm/api-forge/scripts/apply-secrets.sh`
  2. Delete the job: `kubectl delete job postgres-verifier -n api-forge-prod`
  3. Redeploy with Helm: `uv run api-forge-cli deploy up k8s`

### 5. K8s Secret Management & Environment Variable Precedence (HELM DEPLOYMENT)
**Context**: OIDC client secrets flow through multiple layers in Helm-based K8s deployments  
**Secret Flow**:
1. Local files: `infra/secrets/keys/oidc_*_client_secret.txt` (actual values)
2. K8s secrets: Created via `infra/helm/api-forge/scripts/apply-secrets.sh` or CLI (base64 encoded)
3. Volume mounts: `/run/secrets/oidc_*_client_secret` (mounted in pods via Helm templates)
4. Entrypoint script: Copies to `/app/keys/` and creates env vars
5. Application: Reads from entrypoint-created env vars

**Environment Variable Precedence**:
- Entrypoint exports env vars FIRST (from mounted secret files)
- ConfigMap loads env vars AFTER (from `.env` file)
- **Entrypoint values take precedence** and are what the application uses
- When you run `env | grep OIDC` in pod, you see ConfigMap values, but app uses entrypoint values

**Important**: 
- `.env` file should NOT contain real OIDC secrets (removed as of Nov 2025)
- ConfigMap may show placeholder values, but they're not used by the app
- Real secrets only in `infra/secrets/keys/` and K8s secrets
- Helm templates handle all secret mounting automatically
- See `docs/security/secrets_management.md` for complete flow documentation

### 6. Port Conflicts
**Ports Used**: 
- 8000 (FastAPI app)
- 8080 (Keycloak)
- 8082 (Temporal UI)
- 5432 (PostgreSQL - production)
- 5433 (PostgreSQL - development)
- 6379 (Redis - production)
- 6380 (Redis - development)
- 7233 (Temporal)

**Check for conflicts**:
```bash
sudo netstat -tlnp | grep -E ':8080|:5432|:6379|:7233'
```

### 7. Linting Warnings
**Current State**: 36 ruff errors (mostly whitespace/formatting)  
**Safe to ignore** for functionality, but run `uv run ruff check src/ --fix` before committing

## Recent Security Updates (Nov 2025)

- **OIDC nonce + fallback tightening**: `src/app/core/services/oidc_client_service.py` now enforces nonce alignment and only falls back to `userinfo` if an ID token omits required claims. When modifying callback flows (see `src/app/api/http/routers/auth_bff_enhanced.py`), ensure the nonce travels end-to-end.
- **Refresh-token policy guardrails**: `config.yaml` exposes `oidc.refresh_tokens` (modeled by `OIDCRefreshTokenPolicy` in `config_data.py`) so environments can enable/disable refresh handling, opt into persistence, and cap session lifetimes. Always read these flags before storing refresh tokens in Redis-backed sessions.
- **JWKS cache tuning + forced refresh**: `JWTConfig` gained `jwks_cache_ttl_seconds` and `jwks_cache_max_entries`. `JwtVerificationService` can now request `force_refresh=True` when a `kid` is missing—update any mocks/fixtures to accept that kwarg.
- **Logging + session sanitization**: Token/JWT helpers (`jwt_utils.py`, `jwt_verify.py`) only log metadata, never raw claims, and session refresh requests validate lifetimes via `user_session.py`. Preserve this posture when adding new logs or session mutations.

Reference tests: `tests/unit/app/core/services/test_jwt_services.py`, `tests/unit/app/core/services/test_oidc_client_service.py`, and `tests/unit/app/core/services/test_session_service_new.py` cover the behaviors above—extend them when you touch these code paths.

## Future Development Context & Tips

- **CLI-first workflows**: The `api-forge-cli` Typer app is the entrypoint for local env management (`dev start-env`, `dev status`, `dev start-server`), entity scaffolding, and deployments (`deploy up k8s`). Prefer enhancing CLI commands over ad-hoc scripts so contributors follow one path.
- **Config + model parity**: All config surface area lives in `config.yaml` and is validated by `ConfigData` models. When adding a knob, update both the YAML defaults and the corresponding Pydantic model (plus docs under `docs/configuration.md`) and extend tests that rely on the new setting.
- **Database + storage changes**: Until Alembic migrations land, schema adjustments go through `src/app/runtime/init_db.py` and the SQLite dev database. Update fixtures under `tests/fixtures/` and add helper data in `data/` if the change requires dev/test visibility.
- **Testing strategy**: Keep fast unit tests under `tests/unit/` and lean on the provided Redis/Postgres/Temporal containers for integration suites. For anything auth-related, reuse the Keycloak fixtures in `tests/fixtures/auth.py` and avoid hardcoding secrets.
- **Deployment surfaces**: Docker Compose files live in `infra/docker/`, while Helm chart is in `infra/helm/api-forge/`. CI/CD and local deployments use `uv run api-forge-cli deploy up k8s` which handles Helm packaging, config sync (redis.enabled, temporal.enabled), secret creation, and deployment. Ensure any new assets (TLS certs, ConfigMaps, Jobs) are added to the Helm templates and tested through the CLI flow.
- **Observability + logging**: Structured logging defaults to JSON via Loguru. When adding logs, avoid secrets, prefer metadata, and ensure new components emit health info that shows up in `uv run api-forge-cli dev logs <service>`.
- **Stateful services**: Redis (sessions/cache), PostgreSQL (app DB + Temporal), and Temporal itself all have dev/prod splits. For changes touching these systems, note the different ports/secrets and update `docs/redis/`, `docs/postgres/`, or `docs/temporal/` as needed.

---

## Development Environment Test Users

### Keycloak Preloaded Test Users
The development Keycloak service (`api-forge-keycloak-dev`) is automatically configured with test users when you run `uv run api-forge-cli dev start-env`. These users are created by the `src/dev/setup_keycloak.py` script.

**Test Users Available:**
- **Username**: `testuser1`
  - **Email**: testuser1@example.com
  - **Password**: password123
  - **Name**: Test User One
  - **Email Verified**: Yes

- **Username**: `testuser2`
  - **Email**: testuser2@example.com
  - **Password**: password123
  - **Name**: Test User Two
  - **Email Verified**: Yes

**Keycloak Configuration:**
- **Realm**: `test-realm`
- **Client ID**: `test-client`
- **Client Secret**: `test-client-secret`
- **Admin Console**: http://localhost:8080/admin (admin/admin)
- **Redirect URI**: http://localhost:8000/auth/web/callback

**Testing OAuth Flow:**
1. Navigate to http://localhost:8000/auth/web/login?provider=keycloak
2. You'll be redirected to Keycloak login page
3. Login with `testuser1` / `password123`
4. After successful authentication, you'll be redirected back with a session

**Note**: The setup script (`src/dev/setup_keycloak.py`) is idempotent - it will skip creating users/realm/client if they already exist.

---

## Project Architecture & File Locations

### Root Directory Structure
```
/
├── src/                           # Infrastructure source code
│   ├── app/                       # Application code
│   │   ├── api/http/              # FastAPI routers, dependencies
│   │   ├── core/                  # Auth, DB, config, security
│   │   │   ├── models/            # Domain models
│   │   │   ├── services/          # Business logic (OIDC, JWT, sessions)
│   │   │   ├── storage/           # Data access (session storage, DB)
│   │   │   └── security.py        # Security utilities
│   │   ├── entities/              # Domain entities (CLI generates here)
│   │   ├── runtime/               # App initialization & runtime
│   │   │   ├── config/            # Configuration loading & models
│   │   │   └── init_db.py         # Database initialization
│   │   └── service/               # Application services
│   ├── dev/                       # Development tooling
│   │   ├── cli/                   # CLI commands (dev, entity management)
│   │   ├── setup_keycloak.py      # Keycloak setup automation
│   │   └── dev_utils.py           # Development utilities
│   └── utils/                     # Shared utilities
├── tests/                         # Test suites
│   ├── unit/                      # Unit tests
│   ├── integration/               # Integration tests (require Docker)
│   ├── template/                  # Legacy template tests (unused)
│   └── fixtures/                  # Test fixtures
├── docker/                        # Docker configurations
│   ├── dev/                       # Development services
│   │   ├── keycloak/              # Keycloak setup
│   │   ├── postgres/              # PostgreSQL dev config
│   │   ├── redis/                 # Redis dev config
│   │   └── temporal/              # Temporal dev config
│   └── prod/                      # Production services (with TLS/mTLS)
├── docs/                          # Documentation
│   ├── dev_env/                   # Dev environment guides
│   ├── prod/                      # Production deployment
│   └── clients/                   # Client integration examples
├── secrets/                       # Production secrets (gitignored)
├── pyproject.toml                 # Python dependencies & config
├── config.yaml                    # Application configuration
├── .env.example                   # Environment variables template
└── dev.sh                         # Development helper script
```

### Critical Configuration Files

#### `config.yaml` - Main Application Config
- **Location**: `/config.yaml`
- **Format**: YAML with environment variable substitution `${VAR:-default}`
- **Sections**: 
  - `app` - app metadata, sessions, CORS
  - `database` - PostgreSQL/SQLite settings
  - `redis` - cache/session store
  - `temporal` - workflow engine
  - `oidc.providers` - authentication providers (keycloak, google, microsoft)
  - `oidc.refresh_tokens` - governs whether refresh tokens are accepted, persisted, and max session lifetime for refresh flows
  - `jwt` - token validation rules
    - Includes `jwks_cache_ttl_seconds` & `jwks_cache_max_entries` for cache sizing
  - `rate_limiter` - per-endpoint throttling
  - `logging` - structured logging config

#### `pyproject.toml` - Python Project Config
- **Location**: `/pyproject.toml`
- **Package Manager**: Uses `uv` for fast dependency management
- **Python Version**: >=3.13
- **Key Dependencies**: 
  - `fastapi>=0.116.1`
  - `sqlmodel>=0.0.24`
  - `authlib>=1.6.4`
  - `pydantic>=2.11.9`
  - `uvicorn[standard]>=0.35.0`
- **Dev Dependencies**: `pytest`, `ruff`, `mypy`, `pytest-asyncio`
- **Scripts**: 
  - `init-db` - database initialization
  - `cli` - development CLI
- **Ruff Config**: Line length 88, target py313, scope limited to `src/` plus active tooling modules
- **MyPy Config**: Strict type checking enabled
- **Pytest Config**: Auto asyncio mode, marks for manual tests

#### `.env` - Environment Variables
- **Location**: `/.env` (create from `.env.example`)
- **Critical Variables**:
  - `APP_ENVIRONMENT` - development/production/testing
  - `DATABASE_URL` - PostgreSQL connection string
  - `REDIS_URL` - Redis connection string
  - `SESSION_SIGNING_SECRET` - **REQUIRED**, must be changed from default
  - `CSRF_SIGNING_SECRET` - **REQUIRED**, must be changed from default
  - `OIDC_*_CLIENT_SECRET` - Provider OAuth credentials
- **Note**: Development uses separate ports (5433, 6380) from production (5432, 6379)

### Key Source Files

#### `src/app/api/http/app.py` - FastAPI Application
Main application factory and router registration

#### `src/app/api/http/deps.py` - Dependency Injection
FastAPI dependencies for auth, DB, sessions, rate limiting

#### `src/app/runtime/config/config_data.py` - Config Models
Pydantic models for config.yaml validation (464 lines)

#### `src/app/runtime/init_db.py` - Database Initialization
Creates tables, runs migrations

#### `src/app/core/services/oidc_client_service.py` - OIDC Client
Handles OAuth flows, token validation, JWKS caching

#### `src/app/core/services/session_service.py` - Session Management
Session creation, validation, rotation, CSRF protection

#### `src/dev/cli/` - CLI Commands
- `dev_commands.py` - Dev environment management
- `entity_commands.py` - Entity scaffolding

---

## CI/CD & Validation

### GitHub Actions
**Location**: `.github/workflows/ci.yml`

**Workflow**:
1. **Test Job**: Python 3.13, `uv sync --dev`, `uv run pytest -v --cov`
2. **Lint Job**: `ruff check`, `ruff format --check`, `mypy`

**Triggers**: Push to main/develop, PRs to main/develop

### Local Validation Checklist
Before committing changes:
```bash
# 1. Lint and format
uv run ruff check src/ --fix
uv run ruff format src/

# 2. Type check
uv run mypy src/

# 3. Run tests
uv run pytest tests/ -v

# 4. Verify Docker environment works
uv run api-forge-cli dev start-env
uv run api-forge-cli dev status
uv run api-forge-cli dev stop-env
```

---

## Docker Compose Environments

### Development (`docker-compose.dev.yml`)
**Services**: keycloak, keycloak-setup, postgres, redis, temporal, temporal-web  
**Ports**: 8080 (Keycloak), 5433 (PostgreSQL), 6380 (Redis), 7233 (Temporal), 8082 (Temporal UI)  
**Credentials**: All hardcoded (devuser/devpass, admin/admin)  
**Network**: `dev-network` bridge

### Production (`docker-compose.prod.yml`)
**Services**: postgres, redis, temporal, nginx, app  
**Security**: TLS/mTLS, secrets management, SCRAM-SHA-256 auth  
**Ports**: 8000 (Nginx → FastAPI), 5432 (PostgreSQL), 6379 (Redis), 7233 (Temporal)  
**Secrets**: File-based in `/run/secrets/` (see `secrets/generate_secrets.sh`)

---

## Development Workflow Guide

### Adding a New Feature
```bash
# 1. Create feature branch
git checkout -b feature/my-feature

# 2. Generate entity scaffolding (if needed)
uv run api-forge-cli entity add MyEntity
# Follow prompts for fields

# 3. Start dev environment
uv run api-forge-cli dev start-env
uv run api-forge-cli dev start-server

# 4. Make changes, add tests
# Edit src/app/entities/my_entity/...

# 5. Run tests
uv run pytest tests/unit/app/entities/my_entity/ -v

# 6. Lint and format
uv run ruff check src/ --fix
uv run ruff format src/

# 7. Commit and push
git add .
git commit -m "feat: add MyEntity"
git push origin feature/my-feature
```

### Debugging Tips
```bash
# View real-time logs
uv run api-forge-cli dev logs [service_name]

# Access PostgreSQL
docker exec -it api-forge-postgres-dev psql -U postgres

# Access Redis CLI
docker exec -it api-forge-redis-dev redis-cli

# Check Keycloak config
curl http://localhost:8080/realms/test-realm/.well-known/openid-configuration

# Test Temporal UI
open http://localhost:8082
```

---

## Near-Term Roadmap

This template evolves quickly. Here are the highest-priority improvements we plan to deliver next so you can align any workstreams accordingly.

1. **Kubernetes deployment hardening (in progress)**  
  - Auto-trigger `postgres-verifier` after every `uv run api-forge-cli deploy up k8s`
  - Add secret rotation helpers and smoke tests that validate TLS assets before rollout  
  - Finish wiring status reporting back into the CLI so deploys surface verifier output inline

2. **Observability & alerting pack (ETA: next sprint)**  
  - Ship default OpenTelemetry instrumentation + Tempo/Grafana wiring in `docker-compose.dev.yml` and k8s overlays  
  - Provide structured log shipping examples (Grafana Loki) and alert policies for auth/db regressions

3. **Developer experience polish (backlog)**  
  - New `api-forge-cli doctor` command that checks `.env`, Docker health, and TLS prerequisites  
  - Automated Docker cleanup + artifact pruning hooks to keep local environments slim  
  - Pre-commit config bundling (ruff, mypy, pytest smoke) to standardize contributor workflow

4. **Services security review & hardening (research)**  
  - Inventory all running services to ensure TLS is enforced end-to-end (ingress, PostgreSQL, Redis, Temporal, internal APIs)  
  - Extend `secrets/generate_secrets.sh` (and related docs) to mint cert/key pairs when missing  
  - Document verification steps so contributors can confirm certificate wiring locally before deploying

5. **Database migrations with Alembic (design)**  
  - Introduce Alembic to manage schema drift for both the infrastructure app and generated templates  
  - Wire migration commands into `api-forge-cli` (`upgrade`, `downgrade`, `stamp`) with SQLite + Postgres compatibility  
  - Add CI guardrails that fail when migrations are missing or out-of-date

6. **Additional deployment options (exploration)**  
  - Produce Fly.io deployment guide + automation scripts mirroring the existing Kubernetes workflow  
  - Provide reference manifests/Helm chart tweaks for standard Kubernetes clusters outside our k8s overlays  
  - Ensure secrets, TLS assets, and init jobs (postgres-verifier, TLS bootstrap) adapt cleanly across these targets

7. **Add secret rotation CLI commands (TBD)**  
  - New `api-forge-cli secrets rotate` command to regenerate signing secrets, TLS certs, and database passwords  
  - Update deployment docs to include rotation steps and post-rotation verification checks

Contributions toward any of these items are welcome; just open an issue referencing the roadmap bullet so we can coordinate.

---

## Trust These Instructions

**When working in this repository:**
1. **ALWAYS use `uv run` prefix** for Python commands (uv handles virtualenv automatically)
2. **ALWAYS start dev environment** before integration tests: `uv run api-forge-cli dev start-env`
3. **NEVER run `pip install` directly** - use `uv sync` or `uv add`
4. **Check `.env` file exists** - copy from `.env.example` if missing
5. **Wait 30-60 seconds** after `start-env` for services to be healthy
6. **Use PYTHONPATH=src** when running files directly from `src/`
7. **Run linter before committing**: `uv run ruff check src/ --fix`

**Only search for additional info if:**
- These instructions are incomplete for your specific task
- You encounter an error not documented in "Known Issues"
- You need details on a specific module's internals
- You're working on production deployment (see `docs/PRODUCTION_DEPLOYMENT.md`)

**Common Gotchas:**
- Temporal requires PostgreSQL schemas `temporal` and `temporal_visibility` with proper search_path
- Integration tests will fail if Docker services aren't running
- Some tests marked `@pytest.mark.manual` require user interaction - skip with `-m "not manual"`
- Development and production use different ports (dev offset by 1000: 5433 vs 5432, 6380 vs 6379)
- JWKS fixtures (e.g., `tests/fixtures/services.py::jwks_service_fake`) must accept the `force_refresh` kwarg to stay in sync with `JwksService.fetch_jwks`

