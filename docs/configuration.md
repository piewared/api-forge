# ⚙️ Configuration Guide

This document explains how to configure your project generated from **FastAPI Production Template**.  
It builds on the [README’s Configuration section](../README.md#configuration), adding advanced options and best practices for production deployments.

---

## 🧩 Configuration Layers

1. **`.env` file**
   - Holds environment-specific overrides and secrets.
   - Never committed to version control.
   - Example:  
     ```bash
     APP_ENVIRONMENT=production
     DATABASE_URL=postgresql://user:pass@db:5432/app_db
     SESSION_SIGNING_SECRET=change-this-32-char-secret
     ```

2. **`config.yaml`**
   - Structured defaults with support for environment variable substitution.
   - Provides a single source of truth for all application settings.

3. **Pydantic Configuration Models**
   - At startup, settings are validated and type-coerced.
   - Invalid or missing values will raise configuration errors early.

---

## 🗄️ Database Configuration

```yaml
database:
  url: "${DATABASE_URL:-postgresql+asyncpg://appuser:devpass@postgres:5432/app_db}"
  pool_size: 20
  max_overflow: 10
  pool_timeout: 30
  pool_recycle: 1800
````

### Notes

* **SQLite** is used automatically in development if no `DATABASE_URL` is set.
* Use **connection pooling** (`pool_size`, `max_overflow`) for production performance.
* Set **`pool_recycle`** below your DB server’s connection timeout to avoid idle disconnections.

---

## 🔐 OIDC Authentication

Each OIDC provider supports full auto-discovery via its `issuer` metadata URL.
This allows the app to dynamically fetch authorization, token, and JWKS endpoints.

```yaml
oidc:
  providers:
    keycloak:
      issuer: "${OIDC_KEYCLOAK_ISSUER:-http://localhost:8080/realms/test-realm}"
      client_id: "${OIDC_KEYCLOAK_CLIENT_ID:-test-client}"
      client_secret: "${OIDC_KEYCLOAK_CLIENT_SECRET:-test-secret}"
      scopes: ["openid", "email", "profile"]
    google:
      issuer: "https://accounts.google.com"
      client_id: "${OIDC_GOOGLE_CLIENT_ID}"
      client_secret: "${OIDC_GOOGLE_CLIENT_SECRET}"
      scopes: ["openid", "email", "profile"]
  default_provider: "keycloak"
  global_redirect_uri: "${OIDC_REDIRECT_URI:-http://localhost:8000/auth/web/callback}"
  refresh_tokens:
    enabled: false
    persist_in_session_store: false
    max_session_lifetime_seconds: 86400
```

### Key Behaviors

* **PKCE + nonce** validation enforced.
* Tokens verified via provider JWKS.
* Short-lived auth session stored in Redis; long-lived session cookie issued on success.
* Session cookies are **HttpOnly**, **signed**, and **rotated** on refresh.
* **Refresh tokens disabled by default**. Enable `refresh_tokens.enabled` and `persist_in_session_store` only if your security review deems it necessary.

---

## 🔑 JWT Validation

```yaml
jwt:
  allowed_algorithms: ["RS256", "RS512", "ES256"]
  audiences: ["${JWT_AUDIENCE:-api://default}"]
  claims:
    user_id: "${JWT_CLAIM_USER_ID:-sub}"
    email: "${JWT_CLAIM_EMAIL:-email}"
    roles: "${JWT_CLAIM_ROLES:-roles}"
    groups: "${JWT_CLAIM_GROUPS:-groups}"
  jwks_cache_ttl_seconds: 3600
  jwks_cache_max_entries: 16
```

### Notes

* Claims are **mapped dynamically** for different IdPs.
* Audience lists may contain multiple entries for multi-tenant or multi-client APIs.
* JWKS caching is configurable—tune TTL/max entries for providers with aggressive key rotation.

---

## 🔄 Temporal Workflow Engine

```yaml
temporal:
  enabled: true
  url: "${TEMPORAL_URL:-temporal:7233}"
  namespace: "default"
  task_queue: "default"
  worker:
    enabled: true
    activities_per_second: 10
    max_concurrent_activities: 100
```

### Notes

* Temporal runs automatically via Docker in development.
* Use it for orchestrated workflows and durable background tasks.
* For production, connect to a managed Temporal cluster or Temporal Cloud.

---

## ⚡ Redis Configuration

```yaml
redis:
  enabled: true
  url: "${REDIS_URL:-redis://localhost:6379/0}"
```

Used for:

* Session store
* Rate limiting
* CSRF token caching
* OIDC auth-state tracking

### Production Recommendations

* Require authentication (`requirepass` or ACLs).
* Use `rediss://` for TLS connections.
* Configure persistence (`appendonly yes`) if needed for session durability.

---

## 🚦 Rate Limiting

```yaml
rate_limiter:
  enabled: true
  requests: 10
  window_ms: 5000
  per_endpoint: true
  per_method: true
```

* Default: 10 requests per 5 seconds per endpoint/method.
* Backed by Redis, supports distributed rate limiting.
* Customizable by route decorator or middleware configuration.

---

## 🔒 Session & Cookie Settings

```yaml
app:
  session_signing_secret: "${SESSION_SIGNING_SECRET}"
  session_max_age: ${SESSION_MAX_AGE:-3600}
  cors:
    origins: ["${CLIENT_ORIGINS:-http://localhost:3000}"]
```

### Notes

* Each environment must have a unique `session_signing_secret`.
* Cookies:

  * **HttpOnly** – not readable by JS
  * **SameSite=Lax** by default (for single-site apps)
  * **Secure=true** in production
  * **SameSite=None** required for cross-site SPAs with HTTPS
* Sessions rotate periodically and on refresh to limit hijack risk.

---

## 🧠 Logging

```yaml
logging:
  level: "INFO"
  structured: true
  format: "json"
  rotation:
    enabled: true
    max_bytes: 10485760
    backup_count: 5
```

* JSON logging for structured ingestion (e.g., Loki, Datadog, ELK).
* `rotation` enables file log rollover if you deploy outside containers.
* Override via `LOG_LEVEL=DEBUG` in `.env`.

---

## ✅ Recommended Overrides (Production)

| Setting                  | Description                             | Example                                            |
| ------------------------ | --------------------------------------- | -------------------------------------------------- |
| `APP_ENVIRONMENT`        | Environment mode                        | `production`                                       |
| `BASE_URL`               | Public URL of the API                   | `https://api.example.com`                          |
| `SESSION_SIGNING_SECRET` | Random 32+ char secret                  | Generated per environment                          |
| `OIDC_*`                 | Managed IdP credentials                 | Azure AD, Okta, etc.                               |
| `CLIENT_ORIGINS`         | Comma-separated list of allowed origins | `https://app.example.com`                          |
| `DATABASE_URL`           | Managed PostgreSQL instance             | `postgresql://user:pass@rds.amazonaws.com:5432/db` |
| `REDIS_URL`              | Secure Redis                            | `rediss://user:pass@cache.example.com:6379/0`      |

---

## 🧩 Validation at Startup

During startup:

1. `.env` values are loaded.
2. `config.yaml` is parsed and merged.
3. Pydantic validates all values and sets defaults.
4. A summary of effective settings is logged.
5. Missing critical secrets trigger warnings or abort startup (in production mode).

---

## 📚 See Also

* [README — Configuration Overview](../README.md#configuration)
* [README — Authentication API](../README.md#authentication-api)
* [docs/clients/javascript.md](javascript.md)
* [docs/clients/python.md](python.md)

---
