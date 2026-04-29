"""Unit tests for the BFF authentication router.

These tests exercise the router's HTTP-level behavior — status codes, redirects,
cookie handling, and which collaborator methods are invoked — by mounting only
the BFF router on a minimal FastAPI app and using ``app.dependency_overrides``
to inject mocked services. The global FastAPI app is never booted, so no DB,
Redis, or OIDC provider is required.

Service implementations are tested separately under ``tests/unit/app/core``;
true end-to-end flows are covered in ``tests/integration/test_bff_auth_flow.py``
and ``tests/integration/test_oidc_keycloak.py``.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.api.http.deps import (
    get_auth_session_service,
    get_db_session,
    get_oidc_client_service,
    get_optional_session_user,
    get_user_management_service,
    get_user_session_service,
)
from src.app.api.http.routers.auth_bff_enhanced import router_bff
from src.app.core.models.session import AuthSession, TokenClaims, UserSession
from src.app.core.services.oidc_client_service import TokenResponse
from src.app.entities.core.user import User
from src.app.runtime.config.config_data import (
    ConfigData,
    OIDCProviderConfig,
)
from src.app.runtime.context import with_context

# ---------- Test data fixtures ----------


@pytest.fixture
def provider_config() -> OIDCProviderConfig:
    return OIDCProviderConfig(
        client_id="test-client",
        client_secret="test-secret",
        authorization_endpoint="https://idp.test/authorize",
        token_endpoint="https://idp.test/token",
        userinfo_endpoint="https://idp.test/userinfo",
        end_session_endpoint="https://idp.test/logout",
        issuer="https://idp.test",
        jwks_uri="https://idp.test/.well-known/jwks.json",
        scopes=["openid", "profile", "email"],
        redirect_uri="http://localhost:8000/auth/web/callback",
    )


@pytest.fixture
def bff_config(provider_config: OIDCProviderConfig) -> ConfigData:
    """Minimal config the BFF router needs at runtime."""
    config = ConfigData()
    config.app.environment = "development"
    config.app.csrf_signing_secret = "csrf-secret-for-tests-32-bytes-x"
    config.app.session_signing_secret = "session-secret-for-tests-32-byte"
    config.oidc.providers = {"default": provider_config}
    config.oidc.default_provider = "default"
    config.oidc.refresh_tokens.enabled = True
    config.oidc.refresh_tokens.persist_in_session_store = True
    return config


@pytest.fixture
def authenticated_user() -> User:
    return User(
        id="11111111-1111-1111-1111-111111111111",
        email="user@example.com",
        first_name="First",
        last_name="Last",
    )


@pytest.fixture
def auth_session() -> AuthSession:
    return AuthSession(
        id="auth-session-id",
        pkce_verifier="verifier",
        state="state-123",
        nonce="nonce-456",
        provider="default",
        return_to="/dashboard",
        client_fingerprint_hash="fingerprint-hash",
        created_at=int(time.time()),
        expires_at=int(time.time()) + 600,
    )


@pytest.fixture
def user_session(authenticated_user: User) -> UserSession:
    now = int(time.time())
    return UserSession(
        id="user-session-id",
        user_id=str(authenticated_user.id),
        provider="default",
        client_fingerprint="fingerprint-hash",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=now + 3600,
        created_at=now,
        last_accessed_at=now,
        expires_at=now + 86400,
    )


@pytest.fixture
def token_response() -> TokenResponse:
    return TokenResponse(
        access_token="access-token",
        token_type="Bearer",
        expires_in=3600,
        refresh_token="refresh-token",
        id_token="id-token",
    )


@pytest.fixture
def token_claims(authenticated_user: User) -> TokenClaims:
    now = int(time.time())
    return TokenClaims(
        issuer="https://idp.test",
        subject="provider-subject-123",
        audience="test-client",
        nonce="nonce-456",
        email=authenticated_user.email,
        given_name=authenticated_user.first_name,
        family_name=authenticated_user.last_name,
        expires_at=now + 3600,
        issued_at=now,
    )


# ---------- Service mocks ----------


@pytest.fixture
def mock_auth_session_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_user_session_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_oidc_client_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_user_management_service() -> AsyncMock:
    return AsyncMock()


# ---------- App / client fixtures ----------


@pytest.fixture
def bff_app(
    mock_auth_session_service: AsyncMock,
    mock_user_session_service: AsyncMock,
    mock_oidc_client_service: AsyncMock,
    mock_user_management_service: AsyncMock,
) -> FastAPI:
    """Minimal FastAPI app with the BFF router mounted and deps overridden."""
    app = FastAPI()
    app.include_router(router_bff, prefix="/auth")

    app.dependency_overrides[get_auth_session_service] = (
        lambda: mock_auth_session_service
    )
    app.dependency_overrides[get_user_session_service] = (
        lambda: mock_user_session_service
    )
    app.dependency_overrides[get_oidc_client_service] = lambda: mock_oidc_client_service
    app.dependency_overrides[get_user_management_service] = (
        lambda: mock_user_management_service
    )
    # Default: no authenticated user. Individual tests override per-test.
    app.dependency_overrides[get_optional_session_user] = lambda: None
    # Some downstream deps reference the DB session even on routes that
    # don't use it; provide a placeholder so resolution succeeds.
    app.dependency_overrides[get_db_session] = lambda: MagicMock()

    return app


@pytest.fixture
def bff_client(bff_app: FastAPI, bff_config: ConfigData) -> Generator[TestClient]:
    """TestClient with config context active for the test's duration."""
    with with_context(config_override=bff_config):
        yield TestClient(bff_app)


def _set_authenticated(app: FastAPI, user: User) -> None:
    """Switch the dependency override so /me sees the user as authenticated."""
    app.dependency_overrides[get_optional_session_user] = lambda: user


# ---------- /auth/web/login ----------


class TestInitiateLogin:
    def test_redirects_to_provider_authorization_endpoint(
        self,
        bff_client: TestClient,
        mock_auth_session_service: AsyncMock,
        provider_config: OIDCProviderConfig,
    ) -> None:
        mock_auth_session_service.create_auth_session.return_value = "new-session-id"

        response = bff_client.get("/auth/web/login", follow_redirects=False)

        assert response.status_code == 302
        location = urlparse(response.headers["location"])
        assert (
            f"{location.scheme}://{location.netloc}{location.path}"
            == provider_config.authorization_endpoint
        )

        params = parse_qs(location.query)
        assert params["client_id"] == [provider_config.client_id]
        assert params["response_type"] == ["code"]
        assert params["code_challenge_method"] == ["S256"]
        assert "state" in params
        assert "nonce" in params
        assert "code_challenge" in params

    def test_sets_auth_session_cookie(
        self,
        bff_client: TestClient,
        mock_auth_session_service: AsyncMock,
    ) -> None:
        mock_auth_session_service.create_auth_session.return_value = "new-session-id"

        response = bff_client.get("/auth/web/login", follow_redirects=False)

        assert response.cookies.get("auth_session_id") == "new-session-id"

    def test_creates_auth_session_with_generated_security_params(
        self,
        bff_client: TestClient,
        mock_auth_session_service: AsyncMock,
    ) -> None:
        mock_auth_session_service.create_auth_session.return_value = "new-session-id"

        bff_client.get("/auth/web/login", follow_redirects=False)

        mock_auth_session_service.create_auth_session.assert_awaited_once()
        kwargs = mock_auth_session_service.create_auth_session.call_args.kwargs
        # State, PKCE verifier, and nonce must all be generated and persisted.
        assert kwargs["state"]
        assert kwargs["pkce_verifier"]
        assert kwargs["nonce"]
        assert kwargs["provider"] == "default"
        assert kwargs["client_fingerprint_hash"]

    def test_unknown_provider_returns_400(self, bff_client: TestClient) -> None:
        response = bff_client.get(
            "/auth/web/login?provider=does-not-exist", follow_redirects=False
        )

        assert response.status_code == 400
        assert "Unknown provider" in response.text


# ---------- /auth/web/callback ----------


class TestCallback:
    def test_happy_path_creates_user_session_and_redirects(
        self,
        bff_client: TestClient,
        mock_auth_session_service: AsyncMock,
        mock_oidc_client_service: AsyncMock,
        mock_user_management_service: AsyncMock,
        mock_user_session_service: AsyncMock,
        auth_session: AuthSession,
        token_response: TokenResponse,
        token_claims: TokenClaims,
        authenticated_user: User,
    ) -> None:
        mock_auth_session_service.validate_auth_session.return_value = auth_session
        mock_oidc_client_service.exchange_code_for_tokens.return_value = token_response
        mock_oidc_client_service.get_user_claims.return_value = token_claims
        mock_user_management_service.provision_user_from_claims.return_value = (
            authenticated_user
        )
        mock_user_session_service.create_user_session.return_value = "user-session-id"

        bff_client.cookies.set("auth_session_id", auth_session.id)
        response = bff_client.get(
            f"/auth/web/callback?code=auth-code&state={auth_session.state}",
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == auth_session.return_to
        assert response.cookies.get("user_session_id") == "user-session-id"
        # Single-use auth session is retired and the cookie cleared.
        mock_auth_session_service.mark_auth_session_used.assert_awaited_once_with(
            auth_session.id
        )
        mock_auth_session_service.delete_auth_session.assert_awaited_with(
            auth_session.id
        )

    def test_missing_session_cookie_returns_400(self, bff_client: TestClient) -> None:
        response = bff_client.get(
            "/auth/web/callback?code=c&state=s", follow_redirects=False
        )

        assert response.status_code == 400
        assert "Missing auth session" in response.text

    def test_invalid_state_returns_400(
        self,
        bff_client: TestClient,
        mock_auth_session_service: AsyncMock,
        auth_session: AuthSession,
    ) -> None:
        # Validation failure: service signals "no valid session" by returning None.
        mock_auth_session_service.validate_auth_session.return_value = None

        bff_client.cookies.set("auth_session_id", auth_session.id)
        response = bff_client.get(
            "/auth/web/callback?code=c&state=wrong-state", follow_redirects=False
        )

        assert response.status_code == 400
        assert "Invalid or expired" in response.text

    def test_oidc_error_param_redirects_home_and_clears_session(
        self,
        bff_client: TestClient,
        mock_auth_session_service: AsyncMock,
        auth_session: AuthSession,
    ) -> None:
        mock_auth_session_service.validate_auth_session.return_value = auth_session

        bff_client.cookies.set("auth_session_id", auth_session.id)
        response = bff_client.get(
            f"/auth/web/callback?error=access_denied&state={auth_session.state}",
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/"
        mock_auth_session_service.delete_auth_session.assert_awaited_with(
            auth_session.id
        )

    def test_missing_code_redirects_home_and_clears_session(
        self,
        bff_client: TestClient,
        mock_auth_session_service: AsyncMock,
        auth_session: AuthSession,
    ) -> None:
        mock_auth_session_service.validate_auth_session.return_value = auth_session

        bff_client.cookies.set("auth_session_id", auth_session.id)
        response = bff_client.get(
            f"/auth/web/callback?state={auth_session.state}", follow_redirects=False
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/"
        mock_auth_session_service.delete_auth_session.assert_awaited_with(
            auth_session.id
        )

    def test_token_exchange_failure_redirects_home(
        self,
        bff_client: TestClient,
        mock_auth_session_service: AsyncMock,
        mock_oidc_client_service: AsyncMock,
        auth_session: AuthSession,
    ) -> None:
        mock_auth_session_service.validate_auth_session.return_value = auth_session
        mock_oidc_client_service.exchange_code_for_tokens.side_effect = RuntimeError(
            "boom"
        )

        bff_client.cookies.set("auth_session_id", auth_session.id)
        response = bff_client.get(
            f"/auth/web/callback?code=c&state={auth_session.state}",
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/"
        mock_auth_session_service.delete_auth_session.assert_awaited_with(
            auth_session.id
        )

    def test_missing_id_token_redirects_home(
        self,
        bff_client: TestClient,
        mock_auth_session_service: AsyncMock,
        mock_oidc_client_service: AsyncMock,
        auth_session: AuthSession,
    ) -> None:
        mock_auth_session_service.validate_auth_session.return_value = auth_session
        mock_oidc_client_service.exchange_code_for_tokens.return_value = TokenResponse(
            access_token="access-token",
            token_type="Bearer",
            expires_in=3600,
            id_token=None,  # Missing — OIDC requires this.
        )

        bff_client.cookies.set("auth_session_id", auth_session.id)
        response = bff_client.get(
            f"/auth/web/callback?code=c&state={auth_session.state}",
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/"

    def test_user_provisioning_failure_redirects_home(
        self,
        bff_client: TestClient,
        mock_auth_session_service: AsyncMock,
        mock_oidc_client_service: AsyncMock,
        mock_user_management_service: AsyncMock,
        auth_session: AuthSession,
        token_response: TokenResponse,
        token_claims: TokenClaims,
    ) -> None:
        mock_auth_session_service.validate_auth_session.return_value = auth_session
        mock_oidc_client_service.exchange_code_for_tokens.return_value = token_response
        mock_oidc_client_service.get_user_claims.return_value = token_claims
        mock_user_management_service.provision_user_from_claims.side_effect = (
            RuntimeError("db down")
        )

        bff_client.cookies.set("auth_session_id", auth_session.id)
        response = bff_client.get(
            f"/auth/web/callback?code=c&state={auth_session.state}",
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/"


# ---------- /auth/web/me ----------


class TestDebugPage:
    """The /auth/web/debug page renders user-controlled fields into HTML.
    These must be HTML-escaped so a JIT-provisioned user with attacker-
    controlled name/email can't execute JS in another user's session."""

    def test_user_field_html_is_escaped(
        self,
        bff_app: FastAPI,
        bff_client: TestClient,
    ) -> None:
        malicious = User(
            id="ffffffff-ffff-ffff-ffff-ffffffffffff",
            email="evil@example.com",
            first_name="</pre><script>alert(1)</script><pre>",
            last_name="Tester",
        )
        _set_authenticated(bff_app, malicious)
        bff_client.cookies.set("user_session_id", "user-session-id")

        response = bff_client.get("/auth/web/debug")

        assert response.status_code == 200
        body = response.text
        # The literal script tag must NOT appear unescaped — html.escape
        # converts ``<`` to ``&lt;`` and ``>`` to ``&gt;``.
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


class TestAuthState:
    def test_authenticated_returns_user(
        self,
        bff_app: FastAPI,
        bff_client: TestClient,
        authenticated_user: User,
    ) -> None:
        _set_authenticated(bff_app, authenticated_user)
        bff_client.cookies.set("user_session_id", "user-session-id")

        response = bff_client.get("/auth/web/me")

        assert response.status_code == 200
        body = response.json()
        assert body["authenticated"] is True
        assert body["user"]["id"] == str(authenticated_user.id)
        assert body["user"]["email"] == authenticated_user.email
        # CSRF token is generated when a session cookie is present.
        assert body["csrf_token"]

    def test_unauthenticated_returns_blank_state(self, bff_client: TestClient) -> None:
        response = bff_client.get("/auth/web/me")

        assert response.status_code == 200
        body = response.json()
        assert body["authenticated"] is False
        assert body["user"] is None
        assert body["csrf_token"] is None


# ---------- /auth/web/logout ----------


class TestLogout:
    def test_clears_session_and_calls_delete(
        self,
        bff_client: TestClient,
        mock_user_session_service: AsyncMock,
        user_session: UserSession,
    ) -> None:
        mock_user_session_service.get_user_session.return_value = user_session

        bff_client.cookies.set("user_session_id", user_session.id)
        response = bff_client.post("/auth/web/logout")

        assert response.status_code == 200
        mock_user_session_service.delete_user_session.assert_awaited_once_with(
            user_session.id
        )
        # Cookie deletion shows up as a Set-Cookie with empty value / past expiry.
        set_cookie = response.headers.get("set-cookie", "")
        assert "user_session_id=" in set_cookie

    def test_returns_provider_logout_url_when_configured(
        self,
        bff_client: TestClient,
        mock_user_session_service: AsyncMock,
        user_session: UserSession,
        provider_config: OIDCProviderConfig,
    ) -> None:
        mock_user_session_service.get_user_session.return_value = user_session

        bff_client.cookies.set("user_session_id", user_session.id)
        response = bff_client.post("/auth/web/logout")

        body = response.json()
        assert "provider_logout_url" in body
        assert body["provider_logout_url"].startswith(
            provider_config.end_session_endpoint
        )

    def test_without_session_returns_401(self, bff_client: TestClient) -> None:
        response = bff_client.post("/auth/web/logout")

        assert response.status_code == 401

    def test_with_stale_cookie_but_no_session_in_storage(
        self,
        bff_client: TestClient,
        mock_user_session_service: AsyncMock,
    ) -> None:
        """A stale ``user_session_id`` cookie that points at no session in
        storage still results in a successful logout (idempotent), with no
        provider logout URL since no session is found."""
        mock_user_session_service.get_user_session.return_value = None

        bff_client.cookies.set("user_session_id", "stale-session-id")
        response = bff_client.post("/auth/web/logout")

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Logged out"
        assert "provider_logout_url" not in body
        # delete is still called — defense-in-depth, in case the cookie was
        # valid at the cookie level.
        mock_user_session_service.delete_user_session.assert_awaited_once_with(
            "stale-session-id"
        )


# ---------- /auth/web/refresh ----------


class TestRefresh:
    def test_refresh_disabled_returns_404(
        self, bff_app: FastAPI, bff_config: ConfigData
    ) -> None:
        bff_config.oidc.refresh_tokens.enabled = False
        with with_context(config_override=bff_config):
            client = TestClient(bff_app)
            client.cookies.set("user_session_id", "any")
            response = client.post("/auth/web/refresh")

        assert response.status_code == 404

    def test_without_session_returns_401(self, bff_client: TestClient) -> None:
        response = bff_client.post("/auth/web/refresh")
        assert response.status_code == 401

    def test_invalid_session_returns_401_and_clears_cookie(
        self,
        bff_client: TestClient,
        mock_user_session_service: AsyncMock,
    ) -> None:
        mock_user_session_service.validate_user_session.return_value = None

        bff_client.cookies.set("user_session_id", "stale")
        response = bff_client.post("/auth/web/refresh")

        assert response.status_code == 401
        assert "user_session_id=" in response.headers.get("set-cookie", "")

    def test_refresh_internal_failure_returns_401_and_clears_cookie(
        self,
        bff_client: TestClient,
        mock_user_session_service: AsyncMock,
        user_session: UserSession,
    ) -> None:
        mock_user_session_service.validate_user_session.return_value = user_session
        mock_user_session_service.refresh_user_session.side_effect = RuntimeError(
            "provider down"
        )

        bff_client.cookies.set("user_session_id", user_session.id)
        response = bff_client.post("/auth/web/refresh")

        assert response.status_code == 401
        assert "user_session_id=" in response.headers.get("set-cookie", "")

    def test_happy_path_rotates_session_and_returns_csrf(
        self,
        bff_client: TestClient,
        mock_user_session_service: AsyncMock,
        user_session: UserSession,
    ) -> None:
        mock_user_session_service.validate_user_session.return_value = user_session
        mock_user_session_service.refresh_user_session.return_value = (
            "rotated-session-id"
        )

        bff_client.cookies.set("user_session_id", user_session.id)
        response = bff_client.post("/auth/web/refresh")

        assert response.status_code == 200
        body = response.json()
        assert body["csrf_token"]
        # The new session id must be set as the cookie.
        assert "user_session_id=rotated-session-id" in response.headers.get(
            "set-cookie", ""
        )
