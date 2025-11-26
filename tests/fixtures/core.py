from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

import pytest
from fastapi import Response
from sqlalchemy import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from starlette.requests import Request

from src.app.runtime.config.config_data import OIDCProviderConfig
from src.app.runtime.context import get_config
from tests.utils import oct_jwk

# Models will be imported within fixtures to control timing


_HS_KEY = b"router-secret-key"
_ISSUER = "https://issuer.test"
_AUDIENCE = "api://router"
_KID = "router-key"
_NONCE = "test-nonce-value"


@pytest.fixture
def session_nonce() -> str:
    return _NONCE


@pytest.fixture
def provider() -> str:
    return _ISSUER


@pytest.fixture
def issuer() -> str:
    return _ISSUER


@pytest.fixture
def audience() -> str:
    return _AUDIENCE


@pytest.fixture
def secret_for_jwt_generation() -> str:
    return _HS_KEY.decode("utf-8")


@pytest.fixture
def secret_for_jwt_verification() -> str:
    return _HS_KEY.decode("utf-8")


@pytest.fixture
def kid_for_jwt() -> str:
    return _KID


@pytest.fixture
def jwks_data(secret_for_jwt_generation: str, kid_for_jwt: str) -> dict[str, Any]:
    """Mock JWKS data for testing."""
    return {"keys": [oct_jwk(secret_for_jwt_generation.encode("utf-8"), kid_for_jwt)]}


@pytest.fixture
def oidc_provider_config() -> OIDCProviderConfig:
    return OIDCProviderConfig(
        issuer=_ISSUER,
        client_id="test-client-id",
        client_secret="test-client-secret",
        authorization_endpoint=f"{_ISSUER}/authorize",
        token_endpoint=f"{_ISSUER}/token",
        userinfo_endpoint=f"{_ISSUER}/userinfo",
        jwks_uri=f"{_ISSUER}/.well-known/jwks.json",
        scopes=["openid", "profile", "email"],
        redirect_uri="http://localhost/callback",
    )


@pytest.fixture
def request_factory() -> Callable[[dict[str, str]], Request]:
    def _make_request(headers: dict[str, str]) -> Request:
        scope = {
            "type": "http",
            "headers": [
                (name.lower().encode("ascii"), value.encode("latin-1"))
                for name, value in headers.items()
            ],
            "method": "GET",
            "path": "/",
            "query_string": b"",
        }
        return Request(scope)

    return _make_request


@pytest.fixture
def response_factory() -> Callable[[], Any]:
    def _make_response() -> Response:
        return Response(content="", status_code=200)

    return _make_response


@pytest.fixture(scope="session")
def persistent_session() -> Generator[Session]:
    """Create a persistent database session for session-scoped testing."""
    # Create engine first
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Import models to register them with the metadata
    from src.app.entities.core.user import UserTable  # noqa: F401
    from src.app.entities.core.user_identity import UserIdentityTable  # noqa: F401

    # Create all tables using the current metadata state
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


@pytest.fixture
def session() -> Generator[Session]:
    """Create a fresh database session for testing."""
    # Create a unique engine for each test to avoid metadata conflicts
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Import models to register them with the metadata
    # This needs to happen after engine creation but before table creation
    from src.app.entities.core.user import UserTable  # noqa: F401
    from src.app.entities.core.user_identity import UserIdentityTable  # noqa: F401

    # Create all tables - each test gets a fresh database
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        try:
            yield session
        finally:
            # Explicit cleanup
            session.rollback()
            session.close()
            engine.dispose()
