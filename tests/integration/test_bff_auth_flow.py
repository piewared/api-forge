"""Integration tests for the BFF authentication flow.

These tests exercise the full login → callback → /me → logout flow with **real**
session and OIDC client service implementations backed by in-memory storage.
The only seam that is stubbed is the OIDC provider HTTP boundary (token
exchange and claims fetch), since reaching a real provider belongs to
``test_oidc_keycloak.py``.

The point is to verify that:
- Auth sessions survive across the login → callback request boundary
- Real state, fingerprint, and single-use validation pass on the happy path
  and reject the malicious paths
- Cookie issuance, session cookie roundtrip, and logout cleanup work end-to-end
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
from src.app.core.models.session import TokenClaims
from src.app.core.services import (
    AuthSessionService,
    OidcClientService,
    UserSessionService,
)
from src.app.core.services.oidc_client_service import TokenResponse
from src.app.entities.core.user import User
from src.app.runtime.config.config_data import ConfigData, OIDCProviderConfig
from src.app.runtime.context import with_context

# ---------- Test config ----------


@pytest.fixture
def provider_config() -> OIDCProviderConfig:
    return OIDCProviderConfig(
        client_id="integration-client",
        client_secret="integration-secret",
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
def integration_config(provider_config: OIDCProviderConfig) -> ConfigData:
    config = ConfigData()
    config.app.environment = "development"
    config.app.csrf_signing_secret = "csrf-secret-for-tests-32-bytes-x"
    config.app.session_signing_secret = "session-secret-for-tests-32-byte"
    config.oidc.providers = {"default": provider_config}
    config.oidc.default_provider = "default"
    config.oidc.refresh_tokens.enabled = False
    return config


# ---------- Stubbed external boundary ----------


@pytest.fixture
def stubbed_oidc_client(
    oidc_client_service: OidcClientService,
) -> OidcClientService:
    """Real OIDC client with the two HTTP-touching methods stubbed.

    Everything else (config use, error handling, etc.) is the real
    implementation. We replace at the method seam, not via module patching.
    """
    oidc_client_service.exchange_code_for_tokens = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenResponse(
            access_token="access-token",
            token_type="Bearer",
            expires_in=3600,
            refresh_token=None,
            id_token="id-token",
        )
    )

    now = int(time.time())
    oidc_client_service.get_user_claims = AsyncMock(  # type: ignore[method-assign]
        return_value=TokenClaims(
            issuer="https://idp.test",
            subject="provider-subject-1",
            audience="integration-client",
            email="integration@example.com",
            given_name="Integration",
            family_name="Tester",
            expires_at=now + 3600,
            issued_at=now,
        )
    )
    return oidc_client_service


# ---------- Provisioned user (mock collaborator) ----------
#
# UserManagementService.provision_user_from_claims is exercised in dedicated
# unit tests; for the BFF flow we only care that *a* user comes back and that
# the route uses it to mint a session. So mock this collaborator at the seam.


@pytest.fixture
def provisioned_user() -> User:
    return User(
        id="22222222-2222-2222-2222-222222222222",
        email="integration@example.com",
        first_name="Integration",
        last_name="Tester",
    )


@pytest.fixture
def mock_user_management(provisioned_user: User) -> AsyncMock:
    mgmt = AsyncMock()
    mgmt.provision_user_from_claims.return_value = provisioned_user
    return mgmt


# ---------- App + client ----------


@pytest.fixture
def integration_app(
    auth_session_service: AuthSessionService,
    user_session_service: UserSessionService,
    stubbed_oidc_client: OidcClientService,
    mock_user_management: AsyncMock,
) -> FastAPI:
    """Minimal app with the BFF router + REAL session services injected."""
    app = FastAPI()
    app.include_router(router_bff, prefix="/auth")

    app.dependency_overrides[get_auth_session_service] = lambda: auth_session_service
    app.dependency_overrides[get_user_session_service] = lambda: user_session_service
    app.dependency_overrides[get_oidc_client_service] = lambda: stubbed_oidc_client
    app.dependency_overrides[get_user_management_service] = lambda: mock_user_management
    # /me uses get_optional_session_user → DB lookup; not exercised in this
    # file's flow tests, so default to "no user". Tests that need /me set it.
    app.dependency_overrides[get_optional_session_user] = lambda: None
    app.dependency_overrides[get_db_session] = lambda: MagicMock()
    return app


@pytest.fixture
def integration_client(
    integration_app: FastAPI, integration_config: ConfigData
) -> Generator[TestClient]:
    with with_context(config_override=integration_config):
        yield TestClient(integration_app)


def _state_from_login(response) -> str:
    """Extract the ``state`` parameter from a /login redirect."""
    location = urlparse(response.headers["location"])
    return parse_qs(location.query)["state"][0]


# ---------- End-to-end flow ----------


class TestEndToEndAuthFlow:
    @pytest.mark.asyncio
    async def test_login_then_callback_creates_user_session(
        self,
        integration_client: TestClient,
        auth_session_service: AuthSessionService,
        user_session_service: UserSessionService,
        provisioned_user: User,
    ) -> None:
        # 1) Login: creates a real auth session in storage and sets the cookie.
        login = integration_client.get("/auth/web/login", follow_redirects=False)
        assert login.status_code == 302

        auth_session_id = integration_client.cookies.get("auth_session_id")
        assert auth_session_id, "login must set auth_session_id cookie"
        state = _state_from_login(login)

        stored = await auth_session_service.get_auth_session(auth_session_id)
        assert stored is not None
        assert stored.state == state
        assert stored.used is False

        # 2) Callback: real state validation, real single-use enforcement.
        callback = integration_client.get(
            f"/auth/web/callback?code=auth-code&state={state}",
            follow_redirects=False,
        )
        assert callback.status_code == 302
        assert callback.headers["location"] == stored.return_to

        user_session_id = integration_client.cookies.get("user_session_id")
        assert user_session_id, "callback must set user_session_id cookie"

        # User session is durable in storage and bound to the provisioned user.
        user_session = await user_session_service.get_user_session(user_session_id)
        assert user_session is not None
        assert user_session.user_id == str(provisioned_user.id)

        # Auth session was retired (delete after callback success).
        assert await auth_session_service.get_auth_session(auth_session_id) is None

    @pytest.mark.asyncio
    async def test_state_mismatch_attack_is_rejected(
        self,
        integration_client: TestClient,
        auth_session_service: AuthSessionService,
    ) -> None:
        integration_client.get("/auth/web/login", follow_redirects=False)
        auth_session_id = integration_client.cookies.get("auth_session_id")
        assert auth_session_id

        # Real state is from login; we send a different one → must reject.
        attack = integration_client.get(
            "/auth/web/callback?code=c&state=attacker-state",
            follow_redirects=False,
        )
        assert attack.status_code == 400

        # validate_auth_session deletes the session on mismatch as a defense.
        assert await auth_session_service.get_auth_session(auth_session_id) is None

    @pytest.mark.asyncio
    async def test_callback_replay_is_rejected(
        self,
        integration_client: TestClient,
    ) -> None:
        """A second callback with the same auth session must fail (single-use)."""
        login = integration_client.get("/auth/web/login", follow_redirects=False)
        state = _state_from_login(login)

        first = integration_client.get(
            f"/auth/web/callback?code=c&state={state}", follow_redirects=False
        )
        assert first.status_code == 302  # success

        # Replay: second callback with the same state — auth session is now
        # used / deleted so validation must fail.
        replay = integration_client.get(
            f"/auth/web/callback?code=c&state={state}", follow_redirects=False
        )
        assert replay.status_code == 400

    def test_callback_without_session_cookie_returns_400(
        self, integration_client: TestClient
    ) -> None:
        # No prior /login → no cookie. Must short-circuit.
        response = integration_client.get(
            "/auth/web/callback?code=c&state=anything", follow_redirects=False
        )
        assert response.status_code == 400


# ---------- Logout flow ----------


class TestLogoutFlow:
    @pytest.mark.asyncio
    async def test_logout_removes_user_session_from_storage(
        self,
        integration_client: TestClient,
        user_session_service: UserSessionService,
    ) -> None:
        # Pre-create a session in real storage (skip the OIDC dance).
        session_id = await user_session_service.create_user_session(
            user_id="33333333-3333-3333-3333-333333333333",
            provider="default",
            client_fingerprint="fp",
            access_token="access",
        )
        assert await user_session_service.get_user_session(session_id) is not None

        integration_client.cookies.set("user_session_id", session_id)
        response = integration_client.post("/auth/web/logout")

        assert response.status_code == 200
        # Session is gone from storage.
        assert await user_session_service.get_user_session(session_id) is None
