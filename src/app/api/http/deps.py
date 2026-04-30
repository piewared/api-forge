"""FastAPI dependency implementations."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request
from loguru import logger
from sqlmodel import Session

from src.app.api.http.app_data import ApplicationDependencies
from src.app.core.security import validate_csrf_token
from src.app.core.services import (
    AuthSessionService,
    JWKSCache,
    JwksService,
    JwtVerificationService,
    OidcClientService,
    OrphanedIdentityError,
    RedisService,
    TemporalClientService,
    UserManagementService,
    UserSessionService,
)
from src.app.entities.core.user import User, UserRepository
from src.app.runtime.context import get_config


def get_db_session(request: Request) -> Session:
    """Get the database session instance."""
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    return app_deps.database_service.get_session()


def get_jwks_cache(request: Request) -> JWKSCache:
    """Get the JWKS cache instance."""
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    return app_deps.jwks_cache


def get_jwks_service(request: Request) -> JwksService:
    """Get the JWKS service instance."""
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    return app_deps.jwks_service


def get_jwt_verify_service(request: Request) -> JwtVerificationService:
    """Get the JWT verification service instance."""
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    return app_deps.jwt_verify_service


def get_user_session_service(request: Request) -> UserSessionService:
    """Get the User Session service instance."""
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    return app_deps.user_session_service


def get_auth_session_service(request: Request) -> AuthSessionService:
    """Get the Auth Session service instance."""
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    return app_deps.auth_session_service


def get_oidc_client_service(request: Request) -> OidcClientService:
    """Get the OIDC Client service instance."""
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    return app_deps.oidc_client_service


def get_temporal_service(request: Request) -> TemporalClientService:
    """Get the Temporal Client service instance."""
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    return app_deps.temporal_service


def get_redis_service(request: Request) -> RedisService | None:
    """Get the Redis service instance."""
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    return app_deps.redis_service


def get_user_management_service(
    request: Request,
    user_session_service: UserSessionService = Depends(get_user_session_service),
    jwt_verify_service: JwtVerificationService = Depends(get_jwt_verify_service),
    db_session: Session = Depends(get_db_session),
) -> UserManagementService:
    """Get the User Management service instance."""
    user_mgmt_service = UserManagementService(
        user_session_service, jwt_verify_service, db_session
    )
    return user_mgmt_service


# Add your application-specific repository dependencies here
# Example:
# def get_your_repo(db: Session = Depends(get_db_session)) -> YourRepository:
#     return YourRepository(db)


async def get_current_user(
    request: Request,
    jwt_verify: JwtVerificationService = Depends(get_jwt_verify_service),
    user_mgmt: UserManagementService = Depends(get_user_management_service),
) -> User:
    """Authenticate the request using a Bearer token, with JIT user provisioning.

    Token verification stays here (HTTP concern). Provisioning — looking up an
    identity row, creating ``User`` / ``UserIdentity`` records, applying name
    fallbacks — is delegated to :class:`UserManagementService` so the same
    logic isn't duplicated in :func:`get_authenticated_user`.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = auth_header.split(" ", 1)[1]
    claims = await jwt_verify.verify_jwt(token)

    if not claims.issuer or not claims.subject:
        raise HTTPException(
            status_code=401, detail="JWT missing required issuer or subject claims"
        )

    try:
        user = await user_mgmt.provision_user_from_claims(claims)
    except OrphanedIdentityError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    request.state.claims = claims
    request.state.scopes = claims.scopes
    request.state.roles = claims.roles
    request.state.uid = claims.uid
    return user


def require_scope(
    required_scope: str,
) -> Callable[[Request], Coroutine[Any, Any, None]]:
    """Create a dependency that requires a specific scope for the authenticated user."""

    async def dep(request: Request) -> None:
        scopes: set[str] = getattr(request.state, "scopes", set())
        if required_scope not in scopes:
            raise HTTPException(
                status_code=403, detail=f"Missing required scope: {required_scope}"
            )

    return dep


def require_role(required_role: str) -> Callable[[Request], Coroutine[Any, Any, None]]:
    """Create a dependency that requires a specific role for the authenticated user."""

    async def dep(request: Request) -> None:
        roles: set[str] = getattr(request.state, "roles", set())
        if required_role not in roles:
            raise HTTPException(
                status_code=403, detail=f"Missing required role: {required_role}"
            )

    return dep


async def _authenticate_with_session(
    request: Request,
    db: Session,
    user_session_service: UserSessionService,
    required: bool = False,
) -> User | None:
    """
    Common helper for session-based authentication.

    Args:
        request: FastAPI request object
        db: Database session
        required: If True, raises HTTPException when session is missing/invalid
                 If False, returns None when session is missing/invalid

    Returns:
        User object if authenticated, None if not authenticated and not required

    Raises:
        HTTPException: If required=True and authentication fails
    """

    # Try session-based authentication
    session_id = request.cookies.get("user_session_id")
    if not session_id:
        if required:
            raise HTTPException(status_code=401, detail="Session required")
        return None

    try:
        user_session = await user_session_service.get_user_session(session_id)
        if not user_session:
            if required:
                raise HTTPException(
                    status_code=401, detail="Invalid or expired session"
                )
            return None

        # Load user from database
        user_repo = UserRepository(db)
        user = user_repo.get(str(user_session.user_id))
        if not user:
            if required:
                raise HTTPException(status_code=401, detail="User not found")
            return None

        # Store session info in request state
        request.state.session_id = session_id
        request.state.user_session = user_session
        request.state.auth_method = "session"

        # Set empty scope/role info for session auth (could be extended to store in session)
        request.state.scopes = set()
        request.state.roles = set()
        request.state.uid = None
        request.state.claims = {}

        return user
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception:
        # Don't leak unexpected errors to the client, but make them visible in
        # logs — silent except has been a real source of debugging time.
        logger.exception("Unexpected error during session authentication")
        if required:
            raise HTTPException(
                status_code=401, detail="Session authentication failed"
            ) from None
        return None


async def get_authenticated_user(
    request: Request,
    db: Session = Depends(get_db_session),
    jwt_verify: JwtVerificationService = Depends(get_jwt_verify_service),
    user_session_service: UserSessionService = Depends(get_user_session_service),
    user_mgmt: UserManagementService = Depends(get_user_management_service),
) -> User:
    """
    Unified authentication dependency that works with both JWT and session-based auth.
    JIT user provisioning is supported for JWT auth.

    Authentication priority:
    1. Session cookie (BFF pattern) - for web clients
    2. Bearer token (JWT pattern) - for mobile/API clients
    """

    # Try session-based authentication first (BFF pattern)
    user = await _authenticate_with_session(
        request, db, user_session_service, required=False
    )
    if user:
        return user

    # Try JWT Bearer token authentication (mobile/API pattern)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ", 1)[1]
            claims = await jwt_verify.verify_jwt(token)

            if not claims.issuer or not claims.subject:
                raise HTTPException(
                    status_code=401,
                    detail="JWT missing required issuer or subject claims",
                )

            try:
                user = await user_mgmt.provision_user_from_claims(claims)
            except OrphanedIdentityError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc

            # Store JWT info in request state
            request.state.claims = claims
            request.state.scopes = claims.scopes
            request.state.roles = claims.roles
            request.state.uid = claims.uid
            request.state.auth_method = "jwt"

            return user

        except HTTPException:
            # Re-raise HTTP exceptions (auth failures, 500s for orphaned data)
            raise
        except Exception:
            # JWT verification or downstream lookup failed. Don't surface the
            # specific reason to the client (the generic 401 below covers it),
            # but log so the failure is visible in operations.
            logger.exception("JWT authentication path failed; falling through to 401")

    # No valid authentication found
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide either a session cookie or Bearer token.",
    )


async def get_session_only_user(
    request: Request,
    db: Session = Depends(get_db_session),
    user_session_service: UserSessionService = Depends(get_user_session_service),
) -> User | None:
    """
    Session-only authentication dependency for BFF endpoints.
    Only accepts session cookies, not JWT tokens.
    """
    return await _authenticate_with_session(
        request, db, user_session_service, required=True
    )


async def get_optional_session_user(
    request: Request,
    db: Session = Depends(get_db_session),
    user_session_service: UserSessionService = Depends(get_user_session_service),
) -> User | None:
    """
    Optional session-only authentication dependency for BFF endpoints.
    Returns None if no session is found instead of raising an exception.
    Used for endpoints that need to check auth state without failing on unauthenticated requests.
    """
    return await _authenticate_with_session(
        request, db, user_session_service, required=False
    )


@lru_cache(maxsize=50)
def normalize_origin(origin: str) -> tuple[str, str, int]:
    """Normalize an origin string into a tuple for comparison."""
    parsed = urlparse(origin)
    return (
        parsed.scheme.lower(),
        (parsed.hostname or "").lower(),
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )


@lru_cache(maxsize=1)
def get_allowed_origins() -> set[tuple[str, str, int]]:
    """Get allowed origins from config for CORS checks."""
    cfg = get_config()
    allowed_parsed = {normalize_origin(a) for a in cfg.app.cors.origins}

    return allowed_parsed


def is_origin_allowed(origin: str) -> bool:
    """Compare candidate origin against allowed origins."""
    allowed_origins = get_allowed_origins()
    candidate = normalize_origin(origin)

    return candidate in allowed_origins


# Verbs that mutate server state and therefore require CSRF / Origin checks.
_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Environments where CSRF + Origin enforcement is bypassed for developer
# ergonomics (curl, integration test harnesses, etc.). The configured
# environment must match exactly — if a deployment ships with this set to a
# value other than "production", a startup-time warning is logged so the
# bypass cannot silently hide in misconfigured prod.
_CSRF_BYPASS_ENVIRONMENTS = frozenset({"development", "test"})


def _should_bypass_state_changing_checks(request: Request) -> bool:
    """True if the current request should skip CSRF / Origin enforcement.

    Bypassed when:
    - the verb is not state-changing (GET / HEAD / OPTIONS), or
    - the configured app environment is in ``_CSRF_BYPASS_ENVIRONMENTS``.
    """
    if request.method == "OPTIONS":
        return True
    if request.method not in _STATE_CHANGING_METHODS:
        return True
    return get_config().app.environment in _CSRF_BYPASS_ENVIRONMENTS


def enforce_origin(request: Request) -> None:
    """Enforce Origin/Referer allowlist for state-changing requests.

    Skips CORS preflight (OPTIONS) and read-only verbs. In dev/test
    environments the check is bypassed entirely (see module note about
    ``_CSRF_BYPASS_ENVIRONMENTS``).
    """
    if _should_bypass_state_changing_checks(request):
        return

    allowed_origins = get_allowed_origins()  # normalized list of (scheme, host, port)
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    host_header = request.headers.get("host")
    candidate = origin or referer

    # --- If Origin header present ---
    if origin:
        if origin == "null":
            raise HTTPException(status_code=403, detail="Origin 'null' not allowed")
        if not is_origin_allowed(origin):
            raise HTTPException(status_code=403, detail="Origin not allowed")
        return

    # --- No Origin — fall back to same-host check ---
    if not candidate:
        if host_header:
            try:
                scheme, host, port = normalize_origin(f"https://{host_header}")
                if (scheme, host, port) in allowed_origins:
                    return  # Treat as same-origin
            except Exception:
                pass
        # Fail closed
        raise HTTPException(status_code=403, detail="Missing or invalid Origin")

    # --- Referer fallback ---
    if not is_origin_allowed(candidate):
        raise HTTPException(status_code=403, detail="Referer origin not allowed")


def require_csrf(request: Request) -> None:
    """Require an HMAC CSRF token in the X-CSRF-Token header.

    Skips CORS preflight and read-only verbs. In dev/test environments the
    check is bypassed entirely (see module note about
    ``_CSRF_BYPASS_ENVIRONMENTS``).
    """
    if _should_bypass_state_changing_checks(request):
        return

    csrf_header = request.headers.get("x-csrf-token")
    if not csrf_header:
        raise HTTPException(status_code=403, detail="Missing CSRF token header")

    session_id = request.cookies.get("user_session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="No session found")

    if not validate_csrf_token(session_id, csrf_header):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
