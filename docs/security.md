# 🛡️ Security Guide

This document explains the security model used by **FastAPI Production Template** — including authentication flow, CSRF protection, session handling, and best practices for secure deployments.

It builds on the [README's Authentication section](../README.md#authentication-api) and the [Configuration Guide](./configuration.md).

---

## 🔐 Authentication Model

The template implements a **Backend-for-Frontend (BFF)** architecture using **OpenID Connect (OIDC)** with the Authorization Code + PKCE flow.  
This ensures your frontend never directly handles tokens, and your backend maintains complete control over authentication and sessions.

### Key Concepts

| Concept | Description |
|----------|-------------|
| **OIDC Provider** | External identity service (e.g., Keycloak, Google, Microsoft Azure AD). |
| **PKCE** | Proof Key for Code Exchange — prevents interception of authorization codes. |
| **Nonce** | Random value to bind ID tokens to the original request and prevent replay attacks. |
| **State** | Random CSRF token ensuring callback integrity. |
| **Session Cookie** | HttpOnly secure cookie identifying authenticated users. |

---

## 🧭 Authentication Flow

1. **Login Request**  
   The client (usually a browser) calls `/auth/web/login`, optionally specifying a provider.  
   The server:
   - Generates `state`, `nonce`, and a `code_verifier` (PKCE).
   - Stores them in Redis or in-memory storage (ephemeral auth session with 10-minute TTL).
   - Creates an `auth_session_id` cookie for the client.
   - Redirects the user to the provider's authorization endpoint with:
     ```
     response_type=code
     client_id=...
     redirect_uri=http://localhost:8000/auth/web/callback
     state=<random>
     nonce=<random>
     code_challenge=<PKCE-hash>
     code_challenge_method=S256
     ```

2. **User Authenticates**  
   The user logs into the OIDC provider (e.g., Keycloak, Google).

3. **Callback Exchange**  
   The provider redirects the user back to `/auth/web/callback` with a short-lived authorization code.

   The backend:
   - Validates the returned `state` against the stored auth session.
   - Validates the client fingerprint to prevent session hijacking.
   - Marks the auth session as "used" (single-use enforcement).
   - Exchanges the `code` for tokens using the stored `code_verifier` (PKCE).
   - **Verifies the ID token** signature, issuer, audience, and nonce.
   - Fetches or parses user claims from the ID token or userinfo endpoint.
   - Provisions or updates the user in the database (JIT provisioning).
   - Issues a **secure session cookie** (`user_session_id`) with HttpOnly and Secure flags.
   - Deletes the ephemeral auth session.

4. **Authenticated Session**  
   The browser now carries a secure, HttpOnly session cookie on subsequent requests.
   Sessions are stored server-side with client fingerprinting for additional security.

5. **Logout / Refresh**  
   - `/auth/web/logout` (POST): Invalidates the session and clears cookies. Requires CSRF token and Origin validation.
   - `/auth/web/refresh` (POST): Rotates the session ID and CSRF token. Requires CSRF token and Origin validation.

---

## 🍪 Session Management

Sessions are **server-managed** using secure cookies and Redis (or in-memory fallback) for storage.

### Session Types

**1. Auth Session** (Temporary, during OIDC flow):
- Duration: 10 minutes (600 seconds)
- Cookie: `auth_session_id` 
- Purpose: Store PKCE verifier, state, nonce during authorization
- Single-use: Marked as "used" after token exchange

**2. User Session** (Persistent, after authentication):
- Duration: Configurable via `app.session_max_age` (default: 3600 seconds / 1 hour)
- Cookie: `user_session_id`
- Purpose: Maintain authenticated user state
- Features: Client fingerprinting, token storage, session rotation

### Cookie Security Settings

| Property | Value | Description |
|-----------|-------|--------------|
| **HttpOnly** | `true` | Prevents JavaScript access to cookies (XSS protection). |
| **Secure** | `true` in production | Enforces HTTPS (disabled for localhost in development). |
| **SameSite** | `Lax` | Allows top-level navigation (OAuth callbacks) while blocking CSRF. |
| **Path** | `/` | Cookie available across entire domain. |
| **Max-Age** | Configurable | User session: `app.session_max_age`, Auth session: 600 seconds. |

**Note**: `SameSite=Lax` is optimal for BFF pattern OAuth flows. Use `SameSite=None` only if your frontend is on a different domain (requires `Secure=true`).

### Session Storage

Sessions are stored in **Redis** (with automatic fallback to **in-memory** storage if Redis is unavailable):

- **Auth sessions**: Prefix `auth:`, 10-minute TTL
- **User sessions**: Prefix `user:`, configurable TTL (default 1 hour)
- **Automatic cleanup**: Redis handles TTL expiration automatically
- **Session data**: Pydantic models serialized as JSON

**Storage Features**:
- Automatic Redis connection health checking
- Graceful fallback to in-memory storage
- TTL-based expiration (no manual cleanup needed)
- Session listing and pattern matching capabilities

---

## 🧩 CSRF Protection

Cross-Site Request Forgery (CSRF) protection is implemented using **HMAC-based tokens** bound to sessions and **Origin header validation**.

### Protection Mechanisms

| Mechanism | Description |
|------------|-------------|
| **CSRF Token** | HMAC-based token generated using `csrf_signing_secret` and session ID. |
| **Time-based expiration** | Tokens expire after 12 hours (default) to limit replay window. |
| **Session binding** | CSRF tokens are cryptographically bound to specific session IDs. |
| **Origin validation** | Validates `Origin` or `Referer` headers against allowed origins list. |
| **Header requirement** | Frontend must include token in `X-CSRF-Token` header. |

### CSRF Token Generation

CSRF tokens are generated using HMAC-SHA256:
```
token = timestamp:hmac(session_id + ":" + timestamp, csrf_signing_secret)
```

- Tokens are hour-based (timestamp truncated to hours)
- Maximum age: 12 hours (configurable)
- Constant-time comparison prevents timing attacks

### Usage Flow

1. **Get CSRF token**: Call `/auth/web/me` to receive auth state including `csrf_token`
2. **Include in requests**: Add `X-CSRF-Token` header to state-changing requests (POST, PUT, PATCH, DELETE)
3. **Origin validation**: Ensure correct `Origin` header is sent by browser

### Example

```bash
# Get auth state and CSRF token
CSRF=$(curl -s -b cookies.txt http://localhost:8000/auth/web/me | jq -r '.csrf_token')

# Use token in state-changing request
curl -X POST -b cookies.txt \
  -H "Origin: http://localhost:8000" \
  -H "X-CSRF-Token: $CSRF" \
  -H "Content-Type: application/json" \
  -d '{"data":"value"}' \
  http://localhost:8000/api/v1/resource
```

### Protected Endpoints

The following endpoints require CSRF tokens:
- `POST /auth/web/logout` - Logout user
- `POST /auth/web/refresh` - Refresh session

Custom endpoints can add CSRF protection using:
```python
from src.app.api.http.deps import enforce_origin, require_csrf

@router.post("/protected", dependencies=[Depends(enforce_origin), Depends(require_csrf)])
async def protected_endpoint():
    return {"message": "CSRF protected"}
```

### Failure Conditions

* Missing CSRF token → `403 Forbidden: Missing CSRF token header`
* Invalid/expired CSRF token → `403 Forbidden: Invalid CSRF token`
* Missing or invalid `Origin` header → `403 Forbidden: Origin not allowed`
* Missing session cookie → `401 Unauthorized: No session found`

### Development Mode

CSRF validation is **disabled** in `development` and `test` environments to simplify testing. Always test with `APP_ENVIRONMENT=production` before deployment.

---

## 🕵️ Client Fingerprinting

Each session is bound to a lightweight **client fingerprint** to prevent session hijacking and cookie theft attacks.

### Fingerprint Components

The fingerprint is derived from:
* **User-Agent**: Browser and OS identification string
* **Client IP**: First IP from `X-Forwarded-For`, `X-Real-IP`, `CF-Connecting-IP`, or direct client IP
* **Hashing**: SHA256 hash of combined components

### Fingerprint Flow

1. **Session Creation**: Fingerprint captured during login callback
2. **Storage**: Stored in `UserSession` model (`client_fingerprint` field)
3. **Validation**: Checked on every authenticated request
4. **Comparison**: Constant-time comparison to prevent timing attacks

### Security Benefits

- **Stolen cookie protection**: Cookies used from different devices/locations are rejected
- **Session binding**: Ties sessions to specific client contexts
- **Defense in depth**: Additional layer beyond HttpOnly and Secure cookies

### Implementation Details

```python
# Fingerprint extraction (from src/app/core/security.py)
def extract_client_fingerprint(request: Request) -> str:
    """Extract and hash client fingerprint from request."""
    user_agent = request.headers.get("user-agent")
    
    # Try forwarded headers (proxy-aware)
    forwarded_headers = ["x-forwarded-for", "x-real-ip", "cf-connecting-ip"]
    client_ip = None
    for header in forwarded_headers:
        value = request.headers.get(header)
        if value:
            client_ip = value.split(",")[0].strip()
            break
    
    # Fallback to direct client IP
    if not client_ip and request.client:
        client_ip = request.client.host
    
    return hash_client_fingerprint(user_agent, client_ip)
```

### Limitations

- **NAT/Proxy networks**: Users behind shared IPs may have issues if IP changes
- **Mobile networks**: Cellular IPs can change frequently
- **User-Agent changes**: Browser updates invalidate fingerprint

**Mitigation**: The implementation uses strict matching by default but can be configured for fuzzy matching if needed.

---

## 🔑 JWT & Token Security

The template supports both session-based (BFF) and JWT-based authentication for different client types.

### JWT Validation Process

When a JWT bearer token is provided in the `Authorization` header:

| Validation Step | Description |
| -------------------- | ---------------------------------------- |
| **Signature Verification** | Verifies JWT signature using JWKS from provider. |
| **Algorithm Check** | Ensures algorithm is in allowed list (RS256, RS512, ES256, ES384, HS256). |
| **Issuer Validation** | Confirms token issuer matches expected provider. |
| **Audience Check** | Verifies token audience matches configured audiences. |
| **Expiration Check** | Rejects expired tokens (with clock skew tolerance of 60s). |
| **Not-Before Check** | Ensures token is not used before valid time. |
| **Nonce Validation** | Validates nonce in ID tokens (during callback only). |

### ID Token Verification (OIDC Flow)

During the `/auth/web/callback` flow, ID tokens undergo enhanced validation:

```python
# From auth_bff_enhanced.py callback handler
await jwt_verify_service.verify_jwt(
    token=tokens.id_token,
    expected_nonce=auth_session.nonce,  # Single-use nonce
    expected_issuer=provider_cfg.issuer,
    expected_audience=provider_cfg.client_id,
)
```

**Security guarantees**:
- **Nonce binding**: Prevents ID token replay attacks
- **Single-use enforcement**: Nonce is deleted after first use
- **Signature verification**: Ensures token issued by trusted provider
- **Audience validation**: Confirms token intended for this application

### Token Storage

**Important**: The backend **never stores access tokens or ID tokens long-term**.

- **Auth flow**: Tokens are used once during callback then discarded
- **User sessions**: Only session metadata (and optional refresh tokens) are stored
- **Refresh tokens**: Disabled by default. When enabled, they are persisted only if `oidc.refresh_tokens.persist_in_session_store` is true and are subject to a configurable lifetime cap.
- **JWKS caching**: Public keys cached with configurable TTL to reduce provider requests

### JWKS (JSON Web Key Set) Management

```python
# Automatic JWKS fetching and caching
jwks_cache = JWKSCacheInMemory(
   max_entries=config.jwt.jwks_cache_max_entries,
   ttl_seconds=config.jwt.jwks_cache_ttl_seconds,
)
```

**Features**:
- Automatic key rotation detection with forced refresh on `kid` misses
- Configurable TTL + cache size per environment
- Provider-specific key caching
- Thread-safe operations

### JWT Claims Mapping

Standard OIDC claims are mapped to internal user model:

```yaml
jwt:
  claims:
    user_id: "sub"              # Subject (unique user ID)
    email: "email"              # Email address
    roles: "roles"              # User roles/permissions
    groups: "groups"            # User groups
    scope: "scope"              # OAuth scopes
    name: "name"                # Full name
    preferred_username: "preferred_username"
```

### JIT (Just-In-Time) User Provisioning

When a valid JWT is received from a new user:

1. **Identity lookup**: Check if user identity exists (by `uid` or `issuer:subject`)
2. **Create user**: If new, create user record with claims data
3. **Create identity**: Link identity to user with issuer/subject
4. **Return user**: Authenticate request with provisioned user

This enables **zero-touch onboarding** for federated authentication.

---

## 🚦 Rate Limiting & Abuse Prevention

Rate limiting is implemented via Redis (with in-memory fallback) using sliding window algorithm.

### Configuration

Configure rate limits in `config.yaml`:

```yaml
config:
  rate_limiter:
    requests: 10           # Max requests per window
    window_ms: 5000        # Window size in milliseconds (5 seconds)
    enabled: true          # Enable/disable rate limiting
    per_endpoint: true     # Separate limits per endpoint
    per_method: true       # Separate limits per HTTP method
```

### Rate Limiting Behavior

| Setting | Description | Default |
| -------------- | ------- | ----------------------- |
| `requests`     | Maximum requests allowed in window | 10 |
| `window_ms`    | Time window in milliseconds | 5000 (5 seconds) |
| `enabled`      | Enable rate limiting | true |
| `per_endpoint` | Apply limits per route path | true |
| `per_method`   | Separate GET/POST/etc limits | true |

### Implementation

Rate limiting uses `fastapi-limiter` with Redis backend:

```python
from src.app.api.http.middleware.limiter import get_rate_limiter

@router.post("/api/resource")
async def create_resource(
    rate_limit: None = Depends(get_rate_limiter())  # Uses config defaults
):
    return {"message": "created"}

# Custom rate limit for specific endpoint
@router.post("/api/expensive-operation")
async def expensive_op(
    rate_limit: None = Depends(get_rate_limiter(requests=2, window_ms=60000))  # 2 req/min
):
    return {"message": "processed"}
```

### Rate Limit Response

When rate limit is exceeded:

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json

{
  "detail": "Rate limit exceeded"
}
```

**Headers** (may be included depending on configuration):
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Remaining requests in current window
- `X-RateLimit-Reset`: Timestamp when limit resets

### Key Generation

Rate limit keys are generated based on:
- **Client IP**: From `X-Forwarded-For`, `X-Real-IP`, or direct connection
- **Endpoint**: Route path (if `per_endpoint=true`)
- **Method**: HTTP verb (if `per_method=true`)

Example key: `ratelimit:127.0.0.1:/api/resource:POST`

### Storage Backend

- **Primary**: Redis (shared across multiple instances)
- **Fallback**: In-memory (single instance only, loses state on restart)
- **Automatic detection**: Falls back gracefully if Redis unavailable

### Best Practices

**Production Settings**:
```yaml
# Recommended production rate limits
rate_limiter:
  requests: 100          # 100 requests
  window_ms: 60000       # per minute
  per_endpoint: true
  per_method: true
```

**Authentication Endpoints** (stricter limits):
```yaml
# Login/callback endpoints
requests: 10
window_ms: 60000  # 10 attempts per minute
```

**Public API Endpoints** (more lenient):
```yaml
# Read-only public data
requests: 1000
window_ms: 60000  # 1000 reads per minute
```

---

## 🧰 Security Best Practices

### ✅ Development Environment

* **Use local Keycloak** only for testing - never use development credentials in production
* **Test with HTTPS** using self-signed certificates if testing cross-origin flows
* **Set environment variables**:
  ```bash
  APP_ENVIRONMENT=development
  SESSION_SIGNING_SECRET=dev-secret-change-me
  CSRF_SIGNING_SECRET=dev-csrf-secret-change-me
  ```
* **Development mode relaxations**:
  - CSRF validation disabled
  - Origin validation disabled
  - Secure cookie flag disabled (allows HTTP)
  - Detailed error messages exposed

### ✅ Testing Environment

* **Set environment**:
  ```bash
  APP_ENVIRONMENT=test
  ```
* **Use production-like settings** but with relaxed validation for automated tests
* **Seed test data** with known credentials
* **Mock OIDC providers** to avoid external dependencies

### ✅ Production Deployment

**Critical Security Checklist**:

1. **Environment Configuration**:
   ```bash
   APP_ENVIRONMENT=production
   ```

2. **Generate Strong Secrets**:
   ```bash
   # Use infra/secrets/generate_secrets.sh
   ./infra/secrets/generate_secrets.sh --generate-pki
   
   # Verify secrets
   ./infra/secrets/generate_secrets.sh --verify
   ```

3. **Use Managed Identity Provider**:
   - ✅ Azure AD / Entra ID
   - ✅ Google Workspace
   - ✅ Auth0 / Okta
   - ✅ AWS Cognito
   - ✗ Development Keycloak instance

4. **HTTPS Enforcement**:
   - Enable HTTPS on all endpoints
   - Set `Secure` cookie flag (automatic in production)
   - Use TLS 1.2+ with strong cipher suites
   - Implement HSTS headers

5. **Secret Management**:
   ```yaml
   # Use environment variables or secret management
   session_signing_secret: "${SESSION_SIGNING_SECRET}"  # From secret manager
   csrf_signing_secret: "${CSRF_SIGNING_SECRET}"        # From secret manager
   ```
   - Rotate secrets every 90 days
   - Never commit secrets to version control
   - Use `.env` files (gitignored) or external secret managers
   - Implement secret rotation procedures

6. **CORS Configuration**:
   ```yaml
   app:
     cors:
       origins:
         - "https://app.yourdomain.com"  # Explicit origins only
       allow_credentials: true
   ```
   - **Never use wildcards** (`*`) with credentials
   - List explicit allowed origins
   - Use `https://` URLs only in production

7. **Database Security**:
   - Use connection pooling with reasonable limits
   - Enable SSL/TLS for database connections
   - Use separate database users with minimal privileges
   - Regular backup and recovery testing

8. **Redis Security**:
   - Enable password authentication
   - Use TLS for Redis connections in production
   - Set appropriate `maxmemory` limits
   - Monitor Redis memory usage

9. **Logging & Monitoring**:
   ```yaml
   logging:
     level: "INFO"  # Not DEBUG in production
     format: "json"
   ```
   - Never log sensitive data (tokens, passwords, PII)
   - Use structured JSON logging
   - Set up alerting for authentication failures
   - Monitor rate limit violations

10. **Session Configuration**:
    ```yaml
    app:
      session_max_age: 3600  # 1 hour, adjust based on security requirements
    ```
    - Balance security vs user experience
    - Shorter sessions for sensitive operations
    - Implement session refresh for long-lived applications

### ✅ Operational Security

**Regular Tasks**:

1. **Weekly**:
   - Review authentication logs for anomalies
   - Check rate limit violations
   - Monitor failed login attempts

2. **Monthly**:
   - Rotate CSRF and session signing secrets
   - Review and update CORS origins
   - Audit active user sessions

3. **Quarterly**:
   - Update dependencies (`uv lock --upgrade`)
   - Review security advisories
   - Conduct security testing
   - Rotate database passwords

4. **Annually**:
   - Renew TLS certificates
   - Comprehensive security audit
   - Penetration testing
   - Update security documentation

### ✅ Incident Response

**If secrets are compromised**:

1. **Immediate**: Rotate all affected secrets
2. **Invalidate**: Clear all active sessions
3. **Notify**: Inform affected users
4. **Investigate**: Audit logs for unauthorized access
5. **Document**: Record incident and response

**If session hijacking detected**:

1. **Terminate**: Delete affected session
2. **Force re-authentication**: Require user to log in again
3. **Review**: Check fingerprint validation logs
4. **Enhance**: Consider adding additional security layers

---

## 🧠 Security Responsibilities

| Layer               | Responsibility                                                           |
| ------------------- | ------------------------------------------------------------------------ |
| **Template**        | Provides secure defaults, validated auth/session flows, CSRF protection, and client fingerprinting. |
| **You (Developer)** | Configure secrets properly, set CORS origins, manage OIDC provider credentials, implement business logic security. |
| **Ops / Infra**     | Enforce HTTPS, handle TLS certificate management, secure Redis/PostgreSQL, implement network security, monitor and respond to incidents. |

### Template Security Features

**Provided out-of-the-box**:
- ✅ OIDC Authorization Code + PKCE flow
- ✅ Nonce validation and single-use enforcement
- ✅ Client fingerprinting for session binding
- ✅ HMAC-based CSRF token generation
- ✅ Origin/Referer validation
- ✅ Secure cookie configuration (HttpOnly, Secure, SameSite)
- ✅ JWT signature verification with JWKS
- ✅ Rate limiting with Redis backend
- ✅ Session rotation on refresh
- ✅ JIT user provisioning
- ✅ Automatic Redis/in-memory fallback

**Requires configuration**:
- ⚠️ OIDC provider credentials (`client_id`, `client_secret`)
- ⚠️ Session signing secret (`SESSION_SIGNING_SECRET`)
- ⚠️ CSRF signing secret (`CSRF_SIGNING_SECRET`)
- ⚠️ CORS allowed origins
- ⚠️ Rate limit thresholds
- ⚠️ Session expiration times

### Developer Responsibilities

**You must**:
- Generate and rotate secrets regularly
- Configure production OIDC providers (not dev Keycloak)
- Set appropriate CORS origins (no wildcards in production)
- Implement authorization logic (roles, permissions)
- Handle sensitive data appropriately
- Write secure business logic
- Test security configurations
- Review and update dependencies

**You should not**:
- Store tokens in localStorage (use HttpOnly cookies)
- Expose sensitive data in logs
- Use development credentials in production
- Bypass CSRF protection
- Disable security features without understanding implications

### Operations Responsibilities

**Infrastructure team must**:
- Deploy with HTTPS/TLS
- Manage certificate lifecycle
- Secure Redis with password and TLS
- Secure PostgreSQL with SSL and network isolation
- Implement firewall rules
- Set up monitoring and alerting
- Perform regular security audits
- Implement backup and disaster recovery
- Monitor for security incidents
- Rotate infrastructure secrets

---

## 🔒 Security Testing

### Manual Testing Checklist

**Authentication Flow**:
- [ ] Login redirects to OIDC provider correctly
- [ ] Callback validates state parameter
- [ ] Invalid state is rejected with 400
- [ ] Client fingerprint is validated on callback
- [ ] Session cookie is set with correct attributes
- [ ] Logout clears session and cookies
- [ ] Session refresh rotates session ID

**CSRF Protection**:
- [ ] GET requests work without CSRF token
- [ ] POST without CSRF token returns 403
- [ ] POST with invalid CSRF token returns 403
- [ ] POST with valid CSRF token succeeds
- [ ] CSRF token expires after 12 hours
- [ ] Origin validation rejects invalid origins

**Session Security**:
- [ ] HttpOnly flag prevents JavaScript access
- [ ] Secure flag enforced in production
- [ ] Sessions expire after configured time
- [ ] Changed fingerprint invalidates session
- [ ] Session rotation works on refresh

**Rate Limiting**:
- [ ] Exceeding limit returns 429
- [ ] Rate limits reset after window
- [ ] Per-endpoint limits work independently
- [ ] Per-method limits work independently

### Automated Testing

Run security-focused tests:

```bash
# Unit tests for security functions
uv run pytest tests/unit/app/core/test_security.py -v

# Integration tests for auth flows
uv run pytest tests/integration/test_oidc_keycloak.py -v

# CSRF and Origin validation tests
uv run pytest tests/unit/app/api/test_dependencies.py -v

# Rate limiting tests
uv run pytest tests/unit/app/api/test_ratelimit.py -v
```

### Security Scanning

**Dependencies**:
```bash
# Check for known vulnerabilities
uv run pip-audit

# Update dependencies
uv lock --upgrade
```

**Static Analysis**:
```bash
# Type checking
uv run mypy src/

# Security linting
uv run bandit -r src/
```

**SAST (Static Application Security Testing)**:
- Consider integrating tools like Snyk, Semgrep, or SonarQube
- Run scans in CI/CD pipeline
- Review and remediate findings regularly

---

## 🧩 See Also

* [Configuration Guide](./configuration.md) - Complete configuration reference
* [OIDC Documentation](./oidc/main.md) - OIDC setup and provider configuration
* [Secrets Management](./security/secrets_management.md) - Generate and manage secrets
* [README — Authentication API](../README.md#authentication-api) - API endpoint reference
* [JavaScript Client Guide](./clients/javascript.md) - Frontend integration examples
* [Python Client Guide](./clients/python.md) - Backend-to-backend authentication

---

## 📋 Summary

**Key Security Features**:

1. **🔐 BFF Pattern**: Backend controls all authentication, frontend never handles tokens
2. **🔑 PKCE Flow**: Prevents authorization code interception attacks
3. **🎲 Nonce Validation**: Single-use tokens prevent replay attacks
4. **🍪 Secure Sessions**: HttpOnly, Secure, SameSite cookies with server-side storage
5. **🕵️ Fingerprinting**: Client binding prevents session hijacking
6. **🛡️ CSRF Protection**: HMAC-based tokens with Origin validation
7. **✅ JWT Verification**: Full signature and claims validation with JWKS
8. **🚦 Rate Limiting**: Redis-based abuse prevention with sliding windows
9. **📝 JIT Provisioning**: Automatic user creation from trusted identity providers
10. **🔄 Session Rotation**: Security through session ID rotation on refresh

**Security Layers**:
```
┌─────────────────────────────────────────────────────┐
│ Layer 1: Network (HTTPS/TLS, Firewall)             │
├─────────────────────────────────────────────────────┤
│ Layer 2: Authentication (OIDC, PKCE, Nonce)        │
├─────────────────────────────────────────────────────┤
│ Layer 3: Session Security (Cookies, Fingerprint)   │
├─────────────────────────────────────────────────────┤
│ Layer 4: Request Validation (CSRF, Origin)         │
├─────────────────────────────────────────────────────┤
│ Layer 5: Authorization (JWT, Roles, Scopes)        │
├─────────────────────────────────────────────────────┤
│ Layer 6: Rate Limiting (Redis, Sliding Window)     │
├─────────────────────────────────────────────────────┤
│ Layer 7: Monitoring (Logs, Alerts, Audit)          │
└─────────────────────────────────────────────────────┘
```

**Configuration Checklist**:
- [ ] Set `APP_ENVIRONMENT=production`
- [ ] Generate secrets: `./infra/secrets/generate_secrets.sh`
- [ ] Configure production OIDC provider
- [ ] Set explicit CORS origins (no wildcards)
- [ ] Enable HTTPS with valid TLS certificates
- [ ] Configure Redis with password and TLS
- [ ] Set appropriate rate limits
- [ ] Configure session expiration
- [ ] Set up logging and monitoring
- [ ] Test authentication flows
- [ ] Review security settings

This template provides **defense in depth** with multiple security layers. Each layer is designed to fail securely if bypassed, ensuring robust protection for your application.

