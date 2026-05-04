# API Forge — a FastAPI template that's actually opinionated

[![Python](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Lint](https://img.shields.io/badge/lint-Ruff-informational)
![Types](https://img.shields.io/badge/types-MyPy-informational)
![Tests](https://img.shields.io/badge/tests-pytest-success)

A production-shaped FastAPI template that ships the boring decisions already
made. OIDC + BFF authentication, type-safe persistence, durable workflows,
clean-architecture scaffolding, and your choice of deployment target — all
behind one CLI.

```bash
copier copy --trust gh:piewared/api-forge my-service
cd my-service && uv sync
uv run api-forge-cli dev up        # full stack in Docker, hot reload
```

Open `http://localhost:8000/docs` and you have a running, authenticated,
type-checked API.

---

## What you actually get

**A scaffold that encodes good patterns.** One CLI command produces a fully
wired entity — domain model, persistence model, repository, request/response
DTOs, application service with proper transaction boundaries, and an HTTP
router that's auto-discovered at startup. No edits to `app.py` ever.

```bash
api-forge-cli entity add Order
# → entities/service/order/{entity, table, repository, schemas, service, router}.py
# → endpoints live at /api/v1/orders/ — no wiring required
```

**BFF authentication that's not boilerplate.** OIDC Authorization Code +
PKCE with server-side sessions, HttpOnly signed cookies, CSRF protection,
client fingerprinting, and JWKS-based token validation. Pre-seeded
Keycloak in dev, managed IdP (Google / Microsoft / Okta / Auth0 / Cognito)
in prod via config. The hard parts have already been gotten wrong by
someone else.

**Durable workflows when you need them.** Temporal scaffolding with
typed input/result, auto-discovered workflow + activity registry, and
the canonical "endpoint → service → workflow start" pattern wired in
one command:

```bash
api-forge-cli entity add Order --with-workflow OrderDispatch
# → also generates the workflow module and adds an async dispatch()
#   method to OrderService that starts it with idempotent IDs
```

**Pick your deployment target.** Docker Compose for prod, Kubernetes via
Helm, or Fly.io. Each is an opt-in toggle at template-generation time — if
you don't need k8s, the Helm machinery never lands in your repo.

**Dev/prod parity by default.** The dev stack is the prod stack: same
PostgreSQL, same Redis, same Temporal, same Keycloak (dev only) — all
in Docker Compose, started with one command.

---

## Quick start

### 1. Generate a project

```bash
uv tool install copier         # or: pip install -U copier
copier copy --trust gh:piewared/api-forge my-service
cd my-service
```

Copier asks a handful of questions. The defaults give you a slim project
(no fly, no k8s); opt in to deployment targets you actually use:

| Question                | Default | What it controls                                         |
|-------------------------|---------|----------------------------------------------------------|
| `use_redis`             | yes     | Redis caching, sessions, rate limiting                   |
| `use_temporal`          | yes     | Temporal workflow scaffolding + worker                   |
| `use_postgres`          | no      | Postgres deps + URL (default is SQLite for fast start)   |
| `include_fly_deploy`    | no      | `api-forge-cli fly` command + Fly.io infra adapter       |
| `include_k8s_deploy`    | no      | `api-forge-cli k8s` command + Helm deployer + manifests  |

Toggling these off doesn't comment-out code — entire subtrees are
excluded from the generated project. You only carry what you use.

> ⚠️ Copier needs `--trust` for templates with post-generation hooks.
> The hooks are open source — see `copier.yml` and `scripts/post_gen_setup.py`.

### 2. Install + run

```bash
uv sync
cp .env.example .env
uv run api-forge-cli dev up
```

The dev stack pulls and runs PostgreSQL, Redis, Temporal, Keycloak, and
the API itself in Docker. First run takes a minute or two; subsequent
starts are seconds.

Once healthy:

| What                          | URL                                                       |
|-------------------------------|-----------------------------------------------------------|
| API                           | `http://localhost:8000`                                   |
| Interactive docs              | `http://localhost:8000/docs`                              |
| Keycloak (dev only)           | `http://localhost:8080` &nbsp; (admin / admin)            |
| Temporal UI                   | `http://localhost:8082`                                   |

### 3. Iterate

```bash
api-forge-cli dev logs api      # tail just the API
api-forge-cli dev restart api   # restart after dependency changes
api-forge-cli dev down          # stop everything
```

### 4. Update later

```bash
api-forge-cli update    # pull template improvements; merges with your changes
```

Use `api-forge-cli update` rather than `copier update` directly. The
template renames `src/` → `<package_name>/` after generation, which
Copier doesn't know about; the wrapper handles the rename dance so
Copier's three-way merge sees a tree shaped the way it expects, then
restores the package layout afterwards. Net effect: template changes
land as staged-but-uncommitted edits ready for `git diff --staged` and
your usual review.

---

## CLI tour

Everything lives under `api-forge-cli`. Subcommands group by concern:

```bash
api-forge-cli --help
```

```
dev        Development environment commands
prod       Production Docker Compose commands
k8s        Kubernetes Helm deployment commands       (toggle: include_k8s_deploy)
fly        Fly.io deployment commands                (toggle: include_fly_deploy)
config     Configuration validation
entity     Entity scaffolding (add / rm / ls)
workflow   Temporal workflow scaffolding             (when use_temporal=true)
activity   Temporal activity scaffolding             (when use_temporal=true)
secrets    Secret generation and management
users      Keycloak user management (dev)
```

### Scaffolding

```bash
# CRUD entity — entity / table / repo / schemas / service / router + tests
api-forge-cli entity add Product

# Entity + Temporal workflow, fully wired:
# - service.py auto-imports TemporalClientService and stores it
# - router.py injects the temporal dep via FastAPI
# - service.dispatch(<id>) starts the workflow with an idempotent ID
api-forge-cli entity add Order --with-workflow OrderDispatch

# Standalone workflow / activity — when the work spans multiple entities,
# is scheduled, or isn't tied to a specific entity's lifecycle. Pick an
# orchestrator entity and wire dispatch() there manually.
api-forge-cli workflow add OrderFulfillment   # spans Order + Inventory + Shipment
api-forge-cli activity add send_welcome_email
```

### Iteration

```bash
api-forge-cli dev up              # local Docker Compose, hot reload
api-forge-cli fly sync            # push current code to Fly main app (fast path)
api-forge-cli fly up              # full Fly stack (services + main app)
api-forge-cli k8s up              # deploy via Helm
```

`fly sync` is the tight code-iteration loop: skips the supporting-services
phase and pre-flight, just builds and ships the main app image. `fly up`
is the full reconcile (Redis + Temporal + Postgres + main app).

---

## Architecture, briefly

```
HTTP request
   │
   ▼  router.py        — thin handler: delegates to service
   ▼  service.py       — owns transactions; raises domain errors
   ▼  repository.py    — CRUD against the table
   ▼  table.py         — SQLModel persistence
   ▼  entity.py        — Pydantic domain model with invariants
```

Services own commit/rollback. Routers translate domain errors to HTTP
status codes. Entities never import SQLModel (persistence stays at the
edge). Each new entity follows this shape because the scaffold encodes
it. **[Deep dive →](docs/fastapi-clean-architecture-overview.md)**

For background work, two layers of choice:

| Need                                 | Use                  |
|--------------------------------------|----------------------|
| Durable, retryable, replayable       | **Temporal** (scaffolded) |
| Fire-and-forget after the response   | FastAPI `BackgroundTasks` |

The architecture doc explains the asymmetry and shows the canonical
patterns for both.

---

## Authentication

OIDC Authorization Code + PKCE with server-side sessions:

* All web auth endpoints under `/auth/web` (`login`, `callback`, `me`,
  `refresh`, `logout`).
* HttpOnly + signed session cookies; CSRF token rotated on refresh.
* `redirect_uri` is server-configured — never trusted from the client.
* Client fingerprinting binds sessions to the user agent.
* JWKS-based JWT validation for non-cookie clients (mobile, service-to-
  service).

Dev: pre-seeded Keycloak realm. Prod: configure any managed IdP (Azure AD,
Okta, Auth0, Google, Cognito) by setting `oidc.providers` in `config.yaml`.

**[Auth deep dive →](docs/fastapi-auth-oidc-bff.md)** &nbsp;·&nbsp;
**[Sessions & cookies →](docs/fastapi-sessions-and-cookies.md)**

---

## Configuration

`config.yaml` is the single source of truth, with environment variable
substitution everywhere:

```yaml
database:
  url: "${DATABASE_URL:-sqlite:///./database.db}"
redis:
  enabled: true
  url: "${REDIS_URL:-redis://localhost:6379}"
temporal:
  enabled: true
  url: "${TEMPORAL_URL:-temporal:7233}"
oidc:
  providers:
    google:
      issuer: "${OIDC_GOOGLE_ISSUER:-https://accounts.google.com}"
      client_id: "${OIDC_GOOGLE_CLIENT_ID}"
      client_secret: "${OIDC_GOOGLE_CLIENT_SECRET}"
```

`.env` provides per-environment values. Pydantic models enforce the
shape at startup. Service feature flags (`redis.enabled`, `temporal.enabled`)
are honoured at runtime — disable Temporal and the workflow scaffolds
refuse to run, the worker exits cleanly, and rate-limiting falls back to
in-memory.

**[Configuration reference →](docs/configuration.md)**

---

## Testing

```bash
uv run pytest                  # everything
uv run pytest tests/unit/      # unit only — fast, no infra
uv run pytest tests/integration/   # needs dev stack running
uv run pytest tests/e2e/       # full auth + workflow paths
```

**[Testing strategy →](docs/fastapi-testing-strategy.md)**

---

## Deployment

Three first-class targets, each opt-in via copier:

| Target           | Command                       | When                                  |
|------------------|-------------------------------|---------------------------------------|
| Docker Compose   | `api-forge-cli prod up`       | Single host, simple ops               |
| Kubernetes       | `api-forge-cli k8s up`        | Multi-node, autoscaling, your cluster |
| Fly.io           | `api-forge-cli fly up`        | Managed multi-region, no ops          |

For Fly, `fly sync` is the dev loop — fast iteration on the main app
without touching supporting services.

* **[Docker Compose production →](docs/fastapi-production-deployment-docker-compose.md)**
* **[Kubernetes deployment →](docs/kubernetes/fastapi-kubernetes-deployment.md)**
* **[Fly.io deployment →](docs/fly/fastapi-flyio-kubernetes.md)**

---

## Project structure

```
my-service/
├── my_service/                       # Your application package
│   ├── app/
│   │   ├── api/http/                 # FastAPI factory, middleware, routers
│   │   │   ├── app.py                # Slim create_app() factory
│   │   │   ├── lifespan.py           # Startup/shutdown sequencing
│   │   │   ├── deps.py               # Cross-cutting FastAPI dependencies
│   │   │   └── routers/              # Auth + auto-discovery loader
│   │   ├── core/services/            # Cross-cutting infra (JWT, OIDC, Redis, …)
│   │   ├── entities/                 # Domain entities (CLI scaffolds here)
│   │   │   ├── core/                 # Auth-essential (User, UserIdentity)
│   │   │   └── service/              # Generated CRUD entities
│   │   │       └── <name>/{entity, table, repository, schemas, service, router}.py
│   │   ├── runtime/                  # Config loading, DB init
│   │   └── worker/                   # Temporal workflows + activities
│   └── cli/                          # api-forge-cli commands
├── tests/                            # Unit, integration, e2e
├── docs/                             # Architecture, auth, deployment guides
├── docker-compose.dev.yml            # Dev stack
├── docker-compose.prod.yml           # Prod-shaped Compose stack
├── config.yaml                       # Single-source config with env substitution
└── pyproject.toml
```

---

## Who this is for

A good fit if:
* You're building a backend serving web/SPA clients and want **OIDC sessions
  done correctly** instead of rolling your own.
* You want **production-shaped local dev** — same Postgres, same Redis, same
  Temporal — without a full afternoon of setup.
* You want a scaffold that encodes architectural decisions, so a feature is
  one CLI command instead of seven files of boilerplate.

Probably not a fit if:
* You want a minimal "hello world" REST API with zero infra.
* You don't want Docker in your workflow.
* You're committed to a stack the template doesn't speak (Django, Flask + SQL
  Alchemy classic, etc.).

---

## Documentation

* **[Complete guide](docs/index.md)** — overview, quick start, project structure
* **[Clean architecture](docs/fastapi-clean-architecture-overview.md)** — layering, scaffold patterns, async-work decisions
* **[Authentication & OIDC](docs/fastapi-auth-oidc-bff.md)** — BFF pattern, providers, frontend integration
* **[Sessions & cookies](docs/fastapi-sessions-and-cookies.md)** — CSRF, fingerprinting, rotation
* **[Temporal workflows](docs/fastapi-temporal-workflows.md)** — workflows, activities, schedules
* **[Docker dev environment](docs/fastapi-docker-dev-environment.md)** — service URLs, troubleshooting
* **[Database migrations](docs/database-migrations.md)** — Alembic with auto-discovery
* **[Testing strategy](docs/fastapi-testing-strategy.md)** — unit/integration/e2e
* **[JavaScript OIDC client](docs/examples-javascript-oidc-client.md)** &nbsp;·&nbsp; **[Python OIDC client](docs/examples-python-oidc-client.md)**

---

## Requirements

* Python **3.13+**
* **Docker** & **Docker Compose**
* **uv** (recommended) or **pip** + virtualenv
* **Helm v3** + **kubectl** if generating with `include_k8s_deploy=yes`
* **`fly` CLI** if generating with `include_fly_deploy=yes`

---

## License & support

MIT — see [`LICENSE`](LICENSE).

Bugs and feature requests via GitHub Issues. Questions and ideas via
Discussions.
