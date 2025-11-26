import time
from unittest.mock import patch

import httpx
import pytest

from src.app.core.models.session import TokenClaims
from src.app.core.security import generate_pkce_pair, generate_state
from src.app.core.services import OidcClientService
from src.app.core.services.jwt.jwt_verify import JwtVerificationService
from src.app.core.services.oidc_client_service import TokenResponse
from src.app.runtime.context import with_context


class TestOIDCClientService:
    """Test OIDC client functionality."""

    def test_generate_pkce_pair(self, oidc_client_service: OidcClientService):
        """Test PKCE verifier and challenge generation."""
        verifier, challenge = generate_pkce_pair()

        # Should generate valid PKCE pairs
        assert isinstance(verifier, str) and len(verifier) > 0
        assert isinstance(challenge, str) and len(challenge) > 0

        # Should be different each time
        verifier2, challenge2 = generate_pkce_pair()
        assert verifier != verifier2
        assert challenge != challenge2

    def test_generate_state(self, oidc_client_service: OidcClientService):
        """Test state parameter generation."""
        state1 = generate_state()
        state2 = generate_state()

        assert isinstance(state1, str) and len(state1) > 0
        assert state1 != state2

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_success(
        self,
        oidc_client_service: OidcClientService,
        mock_http_response_factory,
        auth_test_config,
    ):
        """Test successful token exchange."""
        mock_response_data = {
            "access_token": "mock-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "mock-refresh-token",
            "id_token": "mock-id-token",
        }
        mock_response = mock_http_response_factory(mock_response_data)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_response
            )

            with with_context(config_override=auth_test_config):
                result = await oidc_client_service.exchange_code_for_tokens(
                    code="test-auth-code",
                    pkce_verifier="test-verifier",
                    provider="default",
                )

                assert isinstance(result, TokenResponse)
                assert result.access_token == "mock-access-token"
                assert result.token_type == "Bearer"
                assert result.expires_in == 3600

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_http_error(
        self,
        oidc_client_service: OidcClientService,
        mock_http_response_factory,
        auth_test_config,
    ):
        """Test token exchange with HTTP error."""
        mock_response = mock_http_response_factory({}, status_code=400)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_response
            )

            with with_context(config_override=auth_test_config):
                with pytest.raises(httpx.HTTPStatusError):
                    await oidc_client_service.exchange_code_for_tokens(
                        code="test-auth-code",
                        pkce_verifier="test-verifier",
                        provider="default",
                    )

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_with_client_secret(
        self,
        oidc_client_service: OidcClientService,
        mock_http_response_factory,
        auth_test_config,
    ):
        """Test token exchange with client secret authentication."""
        # Configure provider with client secret
        auth_test_config.oidc.providers["default"].client_secret = "test-secret"

        mock_response_data = {
            "access_token": "mock-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "mock-refresh-token",
        }
        mock_response = mock_http_response_factory(mock_response_data)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_response
            )

            with with_context(config_override=auth_test_config):
                result = await oidc_client_service.exchange_code_for_tokens(
                    code="test-auth-code",
                    pkce_verifier="test-verifier",
                    provider="default",
                )

                assert isinstance(result, TokenResponse)
                assert result.access_token == "mock-access-token"

                # Verify client secret was included in Authorization header
                call_args = (
                    mock_client.return_value.__aenter__.return_value.post.call_args
                )
                headers = call_args[1]["headers"]
                assert "Authorization" in headers
                assert headers["Authorization"].startswith("Basic ")

    @pytest.mark.asyncio
    async def test_get_user_claims_from_userinfo_endpoint_when_id_token_missing(
        self,
        base_oidc_provider,
        mock_http_response_factory,
        auth_test_config,
        oidc_client_service: OidcClientService,
        jwt_verify_service: JwtVerificationService,
    ):
        claims = {
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

        """Test extracting user claims from userinfo endpoint when ID token fails."""
        mock_response = mock_http_response_factory(claims)

        with patch.object(jwt_verify_service, "verify_jwt") as mock_verify:
            mock_verify.return_value = None

            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__.return_value.get.return_value = (
                    mock_response
                )

                with with_context(config_override=auth_test_config):
                    result = await oidc_client_service.get_user_claims(
                        access_token="mock-access-token",
                        id_token=None,
                        provider="default",
                    )

                    assert result.issuer == "https://mock-provider.test"
                    assert result.subject == "user-12345"
                    assert result.audience == "test-client-id"
                    assert result.email == "test@example.com"
                    assert result.email_verified is True
                    assert result.given_name == "Test"
                    assert result.family_name == "User"
                    assert result.name == "Test User"
                    assert (
                        result.custom_claims.get("picture")
                        == "https://example.com/avatar.jpg"
                    )

                    # Verify userinfo endpoint was called
                    mock_client.return_value.__aenter__.return_value.get.assert_called_once()
                    call_args = (
                        mock_client.return_value.__aenter__.return_value.get.call_args
                    )
                    assert base_oidc_provider.userinfo_endpoint in call_args[0][0]
                    mock_verify.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_user_claims_invalid_id_token_raises(
        self,
        oidc_client_service: OidcClientService,
        jwt_verify_service: JwtVerificationService,
        auth_test_config,
    ):
        with patch.object(jwt_verify_service, "verify_jwt") as mock_verify:
            mock_verify.side_effect = Exception("JWT verification failed")

            with with_context(config_override=auth_test_config):
                with pytest.raises(Exception, match="JWT verification failed"):
                    await oidc_client_service.get_user_claims(
                        access_token="mock-access-token",
                        id_token="mock-id-token",
                        provider="default",
                        expected_nonce="nonce123",
                    )

    @pytest.mark.asyncio
    async def test_get_user_claims_verifies_id_token_with_expected_params(
        self,
        oidc_client_service: OidcClientService,
        jwt_verify_service: JwtVerificationService,
        auth_test_config,
    ):
        token_claims = TokenClaims.from_jwt_payload(
            {
                "iss": "https://mock-provider.test",
                "sub": "user-12345",
                "aud": "test-client-id",
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
            },
            raw_token="mock-id-token",
        )

        with patch.object(
            jwt_verify_service, "verify_jwt", return_value=token_claims
        ) as mock_verify:
            with with_context(config_override=auth_test_config):
                result = await oidc_client_service.get_user_claims(
                    access_token="mock-access-token",
                    id_token="mock-id-token",
                    provider="default",
                    expected_nonce="nonce123",
                )

        assert result.subject == "user-12345"
        mock_verify.assert_awaited_once()
        _, kwargs = mock_verify.call_args
        assert kwargs["expected_nonce"] == "nonce123"
        assert (
            kwargs["expected_audience"]
            == auth_test_config.oidc.providers["default"].client_id
        )
        assert (
            kwargs["expected_issuer"]
            == auth_test_config.oidc.providers["default"].issuer
        )

    @pytest.mark.asyncio
    async def test_get_user_claims_no_id_token_no_userinfo(
        self,
        oidc_client_service: OidcClientService,
        jwt_verify_service: JwtVerificationService,
        auth_test_config,
    ):
        """Test error handling when both ID token and userinfo fail."""
        # Configure provider without userinfo endpoint
        auth_test_config.oidc.providers["default"].userinfo_endpoint = None

        with patch.object(jwt_verify_service, "verify_jwt") as mock_verify:
            with with_context(config_override=auth_test_config):
                with pytest.raises(ValueError, match="Unable to retrieve user claims"):
                    await oidc_client_service.get_user_claims(
                        access_token="mock-access-token",
                        id_token=None,
                        provider="default",
                    )
            mock_verify.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_access_token_success(
        self,
        oidc_client_service: OidcClientService,
        mock_http_response_factory,
        auth_test_config,
    ):
        """Test successful access token refresh."""
        auth_test_config.oidc.refresh_tokens.enabled = True
        mock_response_data = {
            "access_token": "new-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "new-refresh-token",
        }
        mock_response = mock_http_response_factory(mock_response_data)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_response
            )

            with with_context(config_override=auth_test_config):
                result = await oidc_client_service.refresh_access_token(
                    refresh_token="old-refresh-token", provider="default"
                )

                assert isinstance(result, TokenResponse)
                assert result.access_token == "new-access-token"
                assert result.refresh_token == "new-refresh-token"

                # Verify correct refresh request
                call_args = (
                    mock_client.return_value.__aenter__.return_value.post.call_args
                )
                form_data = call_args[1]["data"]
                assert form_data["grant_type"] == "refresh_token"
                assert form_data["refresh_token"] == "old-refresh-token"

    @pytest.mark.asyncio
    async def test_refresh_access_token_disabled(
        self, oidc_client_service: OidcClientService, auth_test_config
    ):
        auth_test_config.oidc.refresh_tokens.enabled = False

        with with_context(config_override=auth_test_config):
            with pytest.raises(ValueError, match="Refresh tokens are disabled"):
                await oidc_client_service.refresh_access_token(
                    refresh_token="old-refresh-token", provider="default"
                )

    @pytest.mark.asyncio
    async def test_refresh_access_token_http_error(
        self,
        oidc_client_service: OidcClientService,
        mock_http_response_factory,
        auth_test_config,
    ):
        """Test token refresh with HTTP error."""
        mock_response = mock_http_response_factory({}, status_code=400)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post.return_value = (
                mock_response
            )

            with with_context(config_override=auth_test_config):
                with pytest.raises(httpx.HTTPStatusError):
                    await oidc_client_service.refresh_access_token(
                        refresh_token="old-refresh-token", provider="default"
                    )

    def test_token_response_expires_at_property(self):
        """Test TokenResponse expires_at property calculation."""
        import time

        token_response = TokenResponse(
            access_token="test-token", token_type="Bearer", expires_in=3600
        )

        # expires_at should be current time + expires_in
        expected_min = int(time.time()) + 3600 - 2  # Allow 2 seconds tolerance
        expected_max = int(time.time()) + 3600 + 2

        assert expected_min <= token_response.expires_at <= expected_max
