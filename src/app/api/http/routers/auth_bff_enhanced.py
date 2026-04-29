"""Enhanced BFF (Backend-for-Frontend) authentication endpoints with CSRF protection and hardened flows."""

import html
import json
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from loguru import logger
from pydantic import BaseModel

from src.app.api.http.deps import (
    enforce_origin,
    get_auth_session_service,
    get_oidc_client_service,
    get_optional_session_user,
    get_user_management_service,
    get_user_session_service,
    require_csrf,
)
from src.app.core.security import (
    extract_client_fingerprint,
    generate_csrf_token,
    generate_nonce,
    generate_pkce_pair,
    generate_state,
    sanitize_return_url,
)
from src.app.core.services import (
    AuthSessionService,
    OidcClientService,
    UserManagementService,
    UserSessionService,
)
from src.app.entities.core.user import User
from src.app.runtime.context import get_config

router_bff = APIRouter(prefix="/web", tags=["auth-bff"])


class AuthState(BaseModel):
    """Current authentication state for web clients."""

    authenticated: bool
    user: dict[str, Any] | None = None
    csrf_token: str | None = None


def _get_secure_cookie_settings() -> dict[str, Any]:
    """Get secure cookie configuration for OAuth authentication.

    For BFF pattern where the session cookie is first-party to your domain,
    SameSite=Lax is sufficient and preferred. OAuth callbacks are top-level
    GET navigations, which Lax allows.

    SameSite=None is only needed if:
    - Your frontend is on a different domain than your API (cross-site subrequests)
    - You use iframes or embedded contexts
    - You need silent token refresh in background requests

    Security is maintained through multiple layers:
    - httponly=True: Prevents JavaScript access (XSS protection)
    - secure=True: HTTPS only (with localhost exception for dev)
    - samesite=Lax: Allows top-level navigations (OAuth callbacks) but blocks CSRF
    - State parameter validation: Prevents CSRF attacks
    - PKCE flow: Prevents authorization code interception
    - Nonce validation: Prevents token replay attacks
    """
    config = get_config()
    return {
        "httponly": True,
        "secure": config.app.environment == "production",
        "samesite": "lax",  # Sufficient for OAuth redirect flows
        "path": "/",
    }


@router_bff.get("/login")
async def initiate_login(
    request: Request,
    provider: str | None = None,
    return_to: str | None = None,  # post-login navigation (NOT IdP redirect_uri)
    auth_session_service: AuthSessionService = Depends(get_auth_session_service),
) -> RedirectResponse:
    """Initiate OIDC login flow with enhanced security.

    Uses PKCE, nonce, CSRF protection, and client fingerprinting.
    Redirects to the identity provider's authorization endpoint.
    """
    config = get_config()

    if not provider:
        provider = config.oidc.default_provider

    if provider not in config.oidc.providers:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    # Generate security parameters (each request gets unique values)
    pkce_verifier, pkce_challenge = generate_pkce_pair()
    state = generate_state()
    nonce = generate_nonce()  # Single-use: bound to this auth session only

    # Extract client fingerprint for session binding
    client_fingerprint = extract_client_fingerprint(request)

    # Sanitize post-login return destination. Prefer relative paths; allowlist absolute if configured.
    safe_return_uri = sanitize_return_url(
        return_to or "/auth/web/debug",
        allowed_hosts=getattr(config.oidc, "allowed_redirect_hosts", None),
    )

    # Create secure auth session (server-side, short TTL)
    session_id = await auth_session_service.create_auth_session(
        pkce_verifier=pkce_verifier,
        state=state,
        nonce=nonce,
        provider=provider,
        return_to=safe_return_uri,
        client_fingerprint_hash=client_fingerprint,
    )

    # Build authorization URL with nonce (IdP redirect_uri is always server-configured)
    provider_config = config.oidc.providers[provider]
    auth_params = {
        "client_id": provider_config.client_id,
        "response_type": "code",
        "scope": " ".join(provider_config.scopes),
        "redirect_uri": provider_config.redirect_uri,
        "state": state,
        "nonce": nonce,  # OIDC nonce for ID token binding & replay prevention
        "code_challenge": pkce_challenge,
        "code_challenge_method": "S256",
    }

    auth_url = f"{provider_config.authorization_endpoint}?{urlencode(auth_params)}"

    # Set secure session cookie and redirect
    response = RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
    cookie_settings = _get_secure_cookie_settings()
    response.set_cookie(
        key="auth_session_id",
        value=session_id,
        max_age=600,  # 10 minutes for auth flow
        **cookie_settings,
    )

    return response


@router_bff.get("/callback")
async def handle_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    auth_session_service: AuthSessionService = Depends(get_auth_session_service),
    user_session_service: UserSessionService = Depends(get_user_session_service),
    oidc_client_service: OidcClientService = Depends(get_oidc_client_service),
    user_service: UserManagementService = Depends(get_user_management_service),
) -> RedirectResponse:
    """Handle OIDC callback with enhanced security validation.

    Performs comprehensive validation including state, fingerprint,
    ID token (incl. nonce) verification, and secure session creation.
    """
    config = get_config()
    session_id = request.cookies.get("auth_session_id")
    # Avoid logging state/code/session ids to prevent leakage
    logger.debug("Callback received for provider login")

    if not session_id:
        # No linkage to our initiated flow; treat as CSRF / invalid callback
        raise HTTPException(status_code=400, detail="Missing auth session")

    client_fingerprint = extract_client_fingerprint(request)

    # Validate state and fingerprint binding (prevents login CSRF / mix-up)
    auth_session = await auth_session_service.validate_auth_session(
        session_id=session_id,
        state=state,  # may be None => fail validation
        client_fingerprint_hash=client_fingerprint,
    )

    if not auth_session:
        # Ensure no stale session cookie remains
        raise HTTPException(status_code=400, detail="Invalid or expired auth session")

    # If the provider returned an OAuth/OIDC error, we only surface it AFTER
    # we've validated the state/session to avoid error-forcing CSRF.
    if error:
        # Retire the single-use auth session on any terminal outcome
        await auth_session_service.delete_auth_session(session_id)
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.delete_cookie("auth_session_id", path="/")
        # Return generic error (details go to server logs)
        return response

    if not code:
        await auth_session_service.delete_auth_session(session_id)
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.delete_cookie("auth_session_id", path="/")
        return response

    try:
        # Mark session as used ASAP to prevent replay (single-use guarantee)
        await auth_session_service.mark_auth_session_used(session_id)

        # Exchange code for tokens via PKCE
        tokens = await oidc_client_service.exchange_code_for_tokens(
            code=code,
            pkce_verifier=auth_session.pkce_verifier,
            provider=auth_session.provider,
        )

        # --- Require an ID token for OIDC login ---
        if not tokens.id_token:
            await auth_session_service.delete_auth_session(session_id)
            response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
            response.delete_cookie("auth_session_id", path="/")
            return response

        # --- Verify the ID token BEFORE using any claims ---
        # Verify signature, issuer, audience, and nonce. Depending on your jwt_service,
        # you may pass expected_issuer / expected_audience here from provider config.

        provider_cfg = config.oidc.providers[auth_session.provider]
        refresh_policy = config.oidc.refresh_tokens

        # Only after verification do we parse/assemble claims.
        user_claims = await oidc_client_service.get_user_claims(
            access_token=tokens.access_token,
            id_token=tokens.id_token,
            provider=auth_session.provider,
            expected_nonce=auth_session.nonce,
            expected_audience=provider_cfg.client_id,
            expected_issuer=getattr(provider_cfg, "issuer", None),
        )

        # JIT provision or update user
        user = await user_service.provision_user_from_claims(user_claims)

        # Create secure user session
        user_session_id = await user_session_service.create_user_session(
            user_id=user.id,
            provider=auth_session.provider,
            client_fingerprint=client_fingerprint,
            refresh_token=tokens.refresh_token
            if (
                tokens.refresh_token
                and refresh_policy.enabled
                and refresh_policy.persist_in_session_store
            )
            else None,
            access_token=tokens.access_token,
            access_token_expires_at=tokens.expires_at,
        )

        # Note: CSRF token generation could be added here for future enhancements
        # csrf_token = generate_csrf_token(user_session_id)

        # Clean up single-use auth session (retires nonce/state)
        await auth_session_service.delete_auth_session(session_id)

        # Redirect to original destination
        redirect_url = auth_session.return_to or "/"
        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        # Set long-lived secure session cookie
        cookie_settings = _get_secure_cookie_settings()
        response.set_cookie(
            key="user_session_id",
            value=user_session_id,
            max_age=config.app.session_max_age,
            **cookie_settings,
        )

        # Clear the short-lived auth session cookie
        response.delete_cookie("auth_session_id", path="/")

        return response

    except Exception:
        # Retire the auth session on any error path so nonce/state can't be
        # reused. delete_auth_session must not mask the original failure.
        logger.exception("Authentication failed during callback")
        try:
            await auth_session_service.delete_auth_session(session_id)
        except Exception:
            logger.exception("Failed to clean up auth session after callback error")
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.delete_cookie("auth_session_id", path="/")
        return response


@router_bff.post(
    "/logout", dependencies=[Depends(enforce_origin), Depends(require_csrf)]
)
async def logout(
    request: Request,
    response: Response,
    user_session_service: UserSessionService = Depends(get_user_session_service),
) -> dict[str, str]:
    """Logout user with secure session cleanup.

    Requires CSRF token and optionally returns provider logout URL.
    """

    session_id = request.cookies.get("user_session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="No session found")

    # Look up the session for the optional provider-logout URL before deleting
    # it. delete_user_session is best-effort idempotent: a stale cookie that
    # doesn't resolve to a session still results in a successful 200 logout.
    user_session = await user_session_service.get_user_session(session_id)
    await user_session_service.delete_user_session(session_id)
    response.delete_cookie("user_session_id", path="/")

    if user_session is not None:
        provider_config = get_config().oidc.providers.get(user_session.provider)
        if provider_config is not None and provider_config.end_session_endpoint:
            logout_params = {
                "post_logout_redirect_uri": "/auth/web/debug",
                "client_id": provider_config.client_id,
            }
            logout_url = (
                f"{provider_config.end_session_endpoint}?{urlencode(logout_params)}"
            )
            return {"message": "Logged out", "provider_logout_url": logout_url}

    return {"message": "Logged out"}


@router_bff.get("/me")
async def get_auth_state(
    request: Request, user: User | None = Depends(get_optional_session_user)
) -> AuthState:
    """Get current authentication state with CSRF token for web client."""
    if not user:
        return AuthState(authenticated=False)

    # Generate CSRF token for authenticated users
    session_id = request.cookies.get("user_session_id")
    csrf_token = None
    if session_id:
        csrf_token = generate_csrf_token(session_id)

    return AuthState(
        authenticated=True,
        user={
            "id": str(user.id),
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
        },
        csrf_token=csrf_token,
    )


@router_bff.post(
    "/refresh",
    # Two distinct response shapes (dict on success, JSONResponse on error
    # paths so we can clear the cookie on a 401). Disable response_model
    # generation so FastAPI doesn't try to validate the union.
    response_model=None,
    dependencies=[Depends(enforce_origin), Depends(require_csrf)],
)
async def refresh_session(
    request: Request,
    response: Response,
    user_session_service: UserSessionService = Depends(get_user_session_service),
    oidc_client_service: OidcClientService = Depends(get_oidc_client_service),
) -> dict[str, str] | JSONResponse:
    """Refresh user session with CSRF + Origin validation and rotation.

    Requires X-CSRF-Token header; validates client fingerprint; rotates session ID and CSRF token.
    """

    config = get_config()
    refresh_policy = config.oidc.refresh_tokens
    if not (refresh_policy.enabled and refresh_policy.persist_in_session_store):
        raise HTTPException(status_code=404, detail="Refresh tokens are disabled")

    session_id = request.cookies.get("user_session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="No session found")

    # Extract client fingerprint for validation
    client_fingerprint = extract_client_fingerprint(request)

    # Validate session with fingerprint check
    user_session = await user_session_service.validate_user_session(
        session_id=session_id,
        client_fingerprint=client_fingerprint,
    )

    if not user_session:
        # FastAPI discards the injected Response when the route raises, so
        # construct the error response directly to keep the cookie clearance.
        error = JSONResponse(status_code=401, content={"detail": "Invalid session"})
        error.delete_cookie("user_session_id", path="/")
        return error

    try:
        # Refresh tokens and rotate session ID
        new_session_id = await user_session_service.refresh_user_session(
            session_id, oidc_client_service
        )

        # Update session cookie with new ID
        cookie_settings = _get_secure_cookie_settings()
        response.set_cookie(
            key="user_session_id",
            value=new_session_id,
            max_age=config.app.session_max_age,
            **cookie_settings,
        )

        # Rotate CSRF token and return it so the client can update in memory
        new_csrf = generate_csrf_token(new_session_id)
        return {"message": "Session refreshed", "csrf_token": new_csrf}

    except Exception:
        logger.exception("Session refresh failed")
        error = JSONResponse(
            status_code=401, content={"detail": "Session refresh failed"}
        )
        error.delete_cookie("user_session_id", path="/")
        return error


# Debugging endpoint to serve as a default return_to for OIDC callbacks. Displays auth state and renders a simple interface with a logout button.
@router_bff.get("/debug")
async def debug_page(
    request: Request,
    auth_state: AuthState = Depends(get_auth_state),
) -> Response:
    """Simple debug page to display auth state and provide logout button.

    User fields (email / first_name / last_name) and the CSRF token are
    embedded in the rendered HTML / JS. Both must be HTML-escaped to prevent
    a JIT-provisioned user from injecting attacker-controlled markup.
    The CSRF token is also passed via a JS-string interpolation, so it is
    JSON-encoded (which produces a valid quoted JS string literal and
    correctly escapes any quote/backslash/control chars).
    """
    auth_json_safe = html.escape(json.dumps(auth_state.model_dump(), indent=2))
    csrf_token_js = json.dumps(auth_state.csrf_token or "")

    logout_button = ""
    if auth_state.authenticated:
        logout_button = f"""
            <form id="logoutForm" method="POST" action="/auth/web/logout">
                <button type="submit">Logout</button>
            </form>
            <script>
                document.getElementById('logoutForm').addEventListener('submit', async function(e) {{
                    e.preventDefault();
                    try {{
                        const response = await fetch('/auth/web/logout', {{
                            method: 'POST',
                            headers: {{
                                'X-CSRF-Token': {csrf_token_js},
                                'Content-Type': 'application/json'
                            }},
                            credentials: 'same-origin'
                        }});

                        if (response.ok) {{
                            const data = await response.json();
                            if (data.provider_logout_url) {{
                                window.location.href = data.provider_logout_url;
                            }} else {{
                                window.location.reload();
                            }}
                        }} else {{
                            alert('Logout failed: ' + response.statusText);
                        }}
                    }} catch (error) {{
                        alert('Logout error: ' + error.message);
                    }}
                }});
            </script>
        """

    html_content = f"""
    <html>
        <head><title>Auth Debug Page</title></head>
        <body>
            <h1>Authentication State</h1>
            <pre>{auth_json_safe}</pre>
            {logout_button}
        </body>
    </html>
    """
    return Response(content=html_content, media_type="text/html")
