"""OIDC client service for handling authorization code flow with PKCE."""

import httpx
from loguru import logger
from pydantic import BaseModel

from src.app.core.models.session import TokenClaims
from src.app.core.services.jwt.jwt_utils import create_token_claims
from src.app.core.services.jwt.jwt_verify import JwtVerificationService
from src.app.runtime.context import get_config


class TokenResponse(BaseModel):
    """OIDC token response model."""

    access_token: str  # In the OIDC spec, this is always lowercase with an underscore. It refers to the token used to access protected resources for the user.
    token_type: str  # In the OIDC spec, this is always lowercase with an underscore. It indicates the type of token issued, typically "Bearer".
    expires_in: int  # Lifetime in seconds of the access token
    refresh_token: str | None = (
        None  # Optional refresh token to obtain new access tokens
    )
    id_token: str | None = None  # Optional ID token containing user claims

    @property
    def expires_at(self) -> int:
        """Calculate absolute expiry timestamp."""
        import time

        return int(time.time()) + self.expires_in


class OidcClientService:
    """Service for OIDC authorization code flow with PKCE."""

    def __init__(self, jwt_verify_service: JwtVerificationService) -> None:
        self._jwt_verify = jwt_verify_service

    async def exchange_code_for_tokens(
        self, code: str, pkce_verifier: str, provider: str
    ) -> TokenResponse:
        """Exchange authorization code for tokens using PKCE.

        Args:
            code: Authorization code from callback
            pkce_verifier: PKCE code verifier
            provider: OIDC provider identifier

        Returns:
            Token response with access/refresh tokens
        """
        provider_config = get_config().oidc.providers[provider]

        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": provider_config.redirect_uri,
            "client_id": provider_config.client_id,
            "code_verifier": pkce_verifier,
        }

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        # Add client authentication if client secret is configured
        if provider_config.client_secret:
            import base64

            credentials = f"{provider_config.client_id}:{provider_config.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded_credentials}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                provider_config.token_endpoint, data=token_data, headers=headers
            )
            response.raise_for_status()

            token_data = response.json()
            return TokenResponse(**token_data)

    async def get_user_claims(
        self,
        access_token: str,
        id_token: str | None,
        provider: str,
        *,
        expected_nonce: str | None = None,
        expected_audience: str | list[str] | None = None,
        expected_issuer: str | None = None,
    ) -> TokenClaims:
        """Get user claims from ID token or userinfo endpoint.

        Args:
            access_token: Access token for userinfo endpoint.
            id_token: ID token with user claims (optional, but required for nonce binding)
            provider: OIDC provider identifier
            expected_nonce: Nonce that must match the ID token when provided
            expected_audience: Audience constraint for ID token validation
            expected_issuer: Issuer constraint for ID token validation

        Returns:
            User claims dictionary
        """

        # If we have an ID token, decode it for user claims
        provider_config = get_config().oidc.providers[provider]

        if id_token:
            # Validate ID token and extract claims; failures are fatal because nonce binding is broken
            return await self._jwt_verify.verify_jwt(
                id_token,
                expected_nonce=expected_nonce,
                expected_audience=expected_audience or provider_config.client_id,
                expected_issuer=expected_issuer or provider_config.issuer,
            )

        # Fall back to userinfo endpoint only when the provider did not issue an ID token.
        logger.warning(
            "Provider {} returned no ID token; using userinfo fallback", provider
        )
        # The userinfo endpoint is an optional part of the OIDC spec, so not all providers will have it.
        # It provides additional user information that may not be included in the ID token. The format is as follows:
        #
        # {
        #     "sub": "user-12345",
        #     "email": "test@example.com",
        #     "name": "Test User",
        #     "picture": "https://example.com/avatar.jpg"
        # }

        if provider_config.userinfo_endpoint:
            headers = {"Authorization": f"Bearer {access_token}"}

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    provider_config.userinfo_endpoint, headers=headers
                )
                response.raise_for_status()
                claims = response.json()
                return create_token_claims(
                    token=access_token,
                    claims=claims,
                    token_type="access_token",
                    issuer=provider_config.issuer,
                )

        # Best practice is to raise an exception, as this is an unexpected error state.
        raise ValueError(
            "Unable to retrieve user claims - no ID token or userinfo endpoint"
        )

    async def refresh_access_token(
        self, refresh_token: str, provider: str
    ) -> TokenResponse:
        """Refresh access token using refresh token.

        Args:
            refresh_token: Refresh token
            provider: OIDC provider identifier

        Returns:
            New token response
        """
        config = get_config()
        if not config.oidc.refresh_tokens.enabled:
            raise ValueError("Refresh tokens are disabled")

        provider_config = config.oidc.providers[provider]

        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": provider_config.client_id,
        }

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        # Add client authentication if client secret is configured
        if provider_config.client_secret:
            import base64

            credentials = f"{provider_config.client_id}:{provider_config.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded_credentials}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                provider_config.token_endpoint, data=token_data, headers=headers
            )
            response.raise_for_status()

            token_data = response.json()
            return TokenResponse(**token_data)
