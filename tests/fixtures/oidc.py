"""OIDC testing fixtures and utilities."""

import time
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from authlib.jose import JsonWebToken
from fastapi import Request, Response

from src.app.core.models.session import AuthSession, UserSession
from src.app.core.services.oidc_client_service import TokenResponse
from src.app.entities.core.user import User
from src.app.runtime.config.config_data import OIDCProviderConfig


@pytest.fixture
def mock_oidc_provider() -> OIDCProviderConfig:
    """Mock OIDC provider configuration for testing."""
    return OIDCProviderConfig(
        client_id="test-client-id",
        client_secret="test-client-secret",
        authorization_endpoint="https://mock-provider.test/authorize",
        token_endpoint="https://mock-provider.test/token",
        userinfo_endpoint="https://mock-provider.test/userinfo",
        end_session_endpoint="https://mock-provider.test/logout",
        issuer="https://mock-provider.test",
        jwks_uri="https://mock-provider.test/.well-known/jwks.json",
        scopes=["openid", "profile", "email"],
        redirect_uri="http://localhost:8000/auth/web/callback",
    )


@pytest.fixture
def mock_user_claims() -> dict[str, Any]:
    """Mock user claims from OIDC provider."""
    return {
        "iss": "https://mock-provider.test",
        "sub": "user-12345",
        "aud": "test-client-id",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "email": "test@example.com",
        "email_verified": True,
        "given_name": "Test",
        "family_name": "User",
        "name": "Test User",
        "picture": "https://example.com/avatar.jpg",
    }


@pytest.fixture
def mock_user() -> User:
    """Mock user for testing."""
    return User(
        id="93743658555595339",
        email="test@example.com",
        first_name="Test",
        last_name="User",
    )


@pytest.fixture
def mock_pkce_pair() -> tuple[str, str]:
    """Mock PKCE verifier and challenge pair."""
    return ("test-pkce-verifier", "test-pkce-challenge")


@pytest.fixture
def mock_state() -> str:
    """Mock OIDC state parameter."""
    return "test-state-parameter"


@pytest.fixture
def mock_authorization_code() -> str:
    """Mock authorization code from callback."""
    return "test-authorization-code"


@pytest.fixture
def mock_id_token() -> str:
    """Mock JWT ID token."""
    # Simple unsigned JWT for testing
    header = {"alg": "none", "typ": "JWT"}
    payload = {
        "iss": "https://mock-provider.test",
        "sub": "user-12345",
        "aud": "test-client-id",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "email": "test@example.com",
        "given_name": "Test",
        "family_name": "User",
    }
    # Create unsigned token for testing
    token = JsonWebToken(["none"])
    return token.encode(header, payload, "").decode()


@pytest.fixture
def mock_httpx_response():
    """Mock httpx response for testing HTTP calls."""
    from unittest.mock import Mock

    import httpx

    class MockResponse:
        def __init__(self, json_data: dict, status_code: int = 200):
            self._json_data = json_data
            self.status_code = status_code

        def json(self) -> dict:
            return self._json_data

        def raise_for_status(self):
            if self.status_code >= 400:
                # Create minimal mocks for HTTPStatusError
                mock_request = Mock(spec=httpx.Request)
                mock_response = Mock(spec=httpx.Response)
                mock_response.status_code = self.status_code

                raise httpx.HTTPStatusError(
                    f"HTTP {self.status_code}",
                    request=mock_request,
                    response=mock_response,
                )

    return MockResponse


@pytest.fixture
def mock_request_with_cookies():
    """Factory for creating mock FastAPI Request objects with cookies."""

    def _create_request(cookies: dict[str, str] | None = None) -> Request:
        if cookies is None:
            cookies = {}

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(b"host", b"localhost:8000")],
        }

        request = Request(scope)
        request._cookies = cookies

        return request

    return _create_request


@pytest.fixture
def mock_response():
    """Mock FastAPI Response object."""
    return Response()


@pytest.fixture
def oidc_test_config():
    """Test configuration with OIDC provider setup."""
    from src.app.runtime.config.config_data import ConfigData, OIDCConfig

    config = ConfigData()
    config.oidc = OIDCConfig()
    config.oidc.providers = {
        "default": OIDCProviderConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            authorization_endpoint="https://mock-provider.test/authorize",
            token_endpoint="https://mock-provider.test/token",
            userinfo_endpoint="https://mock-provider.test/userinfo",
            issuer="https://mock-provider.test",
            jwks_uri="https://mock-provider.test/.well-known/jwks.json",
            redirect_uri="http://localhost:8000/auth/web/callback",
        )
    }

    return config
