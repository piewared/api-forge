"""Service fixtures for testing."""

from collections.abc import AsyncGenerator
from unittest.mock import Mock

import pytest
from sqlmodel import Session

from src.app.core.services import (
    AuthSessionService,
    InMemoryStorage,
    JWKSCache,
    JWKSCacheInMemory,
    JwksService,
    JwtGeneratorService,
    JwtVerificationService,
    OidcClientService,
    SessionStorage,
    UserManagementService,
    UserSessionService,
)
from src.app.core.services.session.manage_sessions import clear_all_sessions
from src.app.runtime.config.config_data import OIDCProviderConfig


@pytest.fixture
def jwks_cache() -> JWKSCache:
    """Get a JWKS cache instance for testing."""
    return JWKSCacheInMemory()


@pytest.fixture
def jwks_service(jwks_cache: JWKSCache):
    """Get a JWKS service instance for testing with cache cleanup."""
    # Clear cache before test
    jwks_cache.clear_jwks_cache()

    service = JwksService(cache=jwks_cache)
    yield service

    # Clear cache after test
    jwks_cache.clear_jwks_cache()


@pytest.fixture
def jwks_service_fake(jwks_data) -> JwksService:
    """Get a fake JWKS service instance for testing."""

    class MockJwksService(JwksService):
        async def fetch_jwks(
            self, issuer: OIDCProviderConfig, *, force_refresh: bool = False
        ):
            return jwks_data

    return MockJwksService(cache=JWKSCacheInMemory())


@pytest.fixture
def jwt_verify_service(jwks_service_fake: JwksService) -> JwtVerificationService:
    """Get a JWT verification service instance for testing."""
    return JwtVerificationService(jwks_service=jwks_service_fake)


@pytest.fixture
def jwt_generate_service() -> JwtGeneratorService:
    """Get a JWT generation service instance for testing."""
    return JwtGeneratorService()


@pytest.fixture
def oidc_client_service(
    jwt_verify_service: JwtVerificationService,
) -> OidcClientService:
    """Get an OIDC Client service instance for testing."""
    return OidcClientService(jwt_verify_service=jwt_verify_service)


@pytest.fixture
def session_storage() -> SessionStorage:
    """Get a mocked session storage instance for testing."""
    return SessionStorage(storage=InMemoryStorage())


@pytest.fixture
def user_session_service(
    session_storage: SessionStorage, oidc_client_service: OidcClientService
) -> UserSessionService:
    """Get a User Session service instance for testing."""
    return UserSessionService(session_storage=session_storage)


@pytest.fixture
def auth_session_service(session_storage: SessionStorage) -> AuthSessionService:
    """Get an Auth Session service instance for testing."""
    return AuthSessionService(session_storage=session_storage)


@pytest.fixture
def user_management_service(
    user_session_service: UserSessionService,
    jwt_verify_service: JwtVerificationService,
    session: Session,
) -> UserManagementService:
    """Get a User Management service instance for testing."""
    return UserManagementService(
        user_session_service=user_session_service,
        jwt_service=jwt_verify_service,
        db_session=session,
    )


# Mock versions for isolated testing
@pytest.fixture
def mock_jwks_cache() -> Mock:
    """Get a mocked JWKS cache instance for testing."""
    return Mock(spec=JWKSCache)


@pytest.fixture
def mock_jwks_service() -> Mock:
    """Get a mocked JWKS service instance for testing."""
    return Mock(spec=JwksService)


@pytest.fixture
def mock_jwt_verify_service() -> Mock:
    """Get a mocked JWT verification service instance for testing."""
    return Mock(spec=JwtVerificationService)


@pytest.fixture
def mock_user_session_service() -> Mock:
    """Get a mocked User Session service instance for testing."""
    return Mock(spec=UserSessionService)


@pytest.fixture
def mock_auth_session_service() -> Mock:
    """Get a mocked Auth Session service instance for testing."""
    return Mock(spec=AuthSessionService)


@pytest.fixture
def mock_oidc_client_service() -> Mock:
    """Get a mocked OIDC Client service instance for testing."""
    return Mock(spec=OidcClientService)


@pytest.fixture
def mock_user_management_service() -> Mock:
    """Get a mocked User Management service instance for testing."""
    return Mock(spec=UserManagementService)


@pytest.fixture(autouse=True)
async def reset_session_storage(
    session_storage: SessionStorage,
) -> AsyncGenerator[None]:
    """Reset session storage before each test to avoid Redis connection conflicts."""

    await clear_all_sessions(session_storage)
    yield
    # Reset again after test to clean up
    await clear_all_sessions(session_storage)
