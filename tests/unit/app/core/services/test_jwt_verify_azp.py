"""Unit tests for the ``azp`` (authorized party) rule in ``verify_jwt``.

Per OIDC Core and RFC 9068 §2.2, ``azp`` carries the client id of the
authorized party. That client id is normally *not* a member of ``aud``:
Keycloak emits ``aud=['api://default','account']`` with ``azp='test-client'``.

Tokens are minted directly with authlib rather than through
``JwtGeneratorService``, because the generator force-overwrites ``azp`` to
``aud[0]`` for multi-audience tokens and so cannot produce this shape.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from authlib.jose import jwt
from fastapi import HTTPException

from src.app.core.services import JwksService, JwtVerificationService
from src.app.runtime.config.config_data import (
    ConfigData,
    JWTConfig,
    OIDCConfig,
    OIDCProviderConfig,
)
from src.app.runtime.context import with_context

_ISSUER = "https://keycloak.test/realms/test-realm"
_CLIENT_ID = "test-client"
_API_AUDIENCE = "api://default"


@pytest.fixture
def provider() -> OIDCProviderConfig:
    return OIDCProviderConfig(
        client_id=_CLIENT_ID,
        client_secret="test-client-secret",
        authorization_endpoint=f"{_ISSUER}/protocol/openid-connect/auth",
        token_endpoint=f"{_ISSUER}/protocol/openid-connect/token",
        issuer=_ISSUER,
        jwks_uri=f"{_ISSUER}/protocol/openid-connect/certs",
        redirect_uri="http://localhost:8000/auth/web/callback",
    )


@pytest.fixture
def config(provider: OIDCProviderConfig) -> ConfigData:
    return ConfigData(
        oidc=OIDCConfig(providers={"keycloak": provider}),
        jwt=JWTConfig(
            allowed_algorithms=["HS256"],
            audiences=[_API_AUDIENCE, "http://localhost:8000"],
        ),
    )


def _mint(
    secret: str,
    kid: str,
    *,
    aud: str | list[str],
    azp: str | None,
) -> str:
    """Mint a token with full control over aud/azp."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": _ISSUER,
        "sub": "keycloak-user-123",
        "aud": aud,
        "exp": now + 3600,
        "iat": now,
        "nbf": now,
        "email": "user@example.com",
    }
    if azp is not None:
        payload["azp"] = azp

    return jwt.encode(
        {"alg": "HS256", "typ": "JWT", "kid": kid}, payload, secret
    ).decode("ascii")


async def _verify(
    service: JwtVerificationService, config: ConfigData, token: str
) -> Any:
    with with_context(config_override=config):
        return await service.verify_jwt(token, expected_issuer=_ISSUER)


class TestMultiAudienceAzp:
    async def test_keycloak_shaped_token_verifies(
        self,
        jwt_verify_service: JwtVerificationService,
        config: ConfigData,
        secret_for_jwt_generation: str,
        kid_for_jwt: str,
    ) -> None:
        """The regression: azp is the client id, not an audience member.

        Previously rejected with "Invalid azp for multi-audience token",
        which 401'd the entire Bearer path against a stock dev realm.
        """
        token = _mint(
            secret_for_jwt_generation,
            kid_for_jwt,
            aud=[_API_AUDIENCE, "account"],
            azp=_CLIENT_ID,
        )

        claims = await _verify(jwt_verify_service, config, token)

        assert claims.subject == "keycloak-user-123"
        assert claims.audience == [_API_AUDIENCE, "account"]

    async def test_azp_matching_an_audience_still_verifies(
        self,
        jwt_verify_service: JwtVerificationService,
        config: ConfigData,
        secret_for_jwt_generation: str,
        kid_for_jwt: str,
    ) -> None:
        """The pre-existing accepted shape must keep working."""
        token = _mint(
            secret_for_jwt_generation,
            kid_for_jwt,
            aud=[_API_AUDIENCE, "account"],
            azp=_API_AUDIENCE,
        )

        claims = await _verify(jwt_verify_service, config, token)

        assert claims.subject == "keycloak-user-123"

    async def test_unrelated_azp_is_still_rejected(
        self,
        jwt_verify_service: JwtVerificationService,
        config: ConfigData,
        secret_for_jwt_generation: str,
        kid_for_jwt: str,
    ) -> None:
        """The check must not be loosened into a no-op."""
        token = _mint(
            secret_for_jwt_generation,
            kid_for_jwt,
            aud=[_API_AUDIENCE, "account"],
            azp="some-other-client",
        )

        with pytest.raises(HTTPException) as exc:
            await _verify(jwt_verify_service, config, token)

        assert exc.value.status_code == 401
        assert "Invalid azp for multi-audience token" in exc.value.detail

    async def test_missing_azp_on_multi_audience_is_rejected(
        self,
        jwt_verify_service: JwtVerificationService,
        config: ConfigData,
        secret_for_jwt_generation: str,
        kid_for_jwt: str,
    ) -> None:
        token = _mint(
            secret_for_jwt_generation,
            kid_for_jwt,
            aud=[_API_AUDIENCE, "account"],
            azp=None,
        )

        with pytest.raises(HTTPException) as exc:
            await _verify(jwt_verify_service, config, token)

        assert exc.value.status_code == 401
        assert "Missing azp for multi-audience token" in exc.value.detail


class TestGeneratorVerifierRoundTrip:
    """The generator and the verifier must agree on a spec-shaped token.

    Before the azp fixes these two disagreed: the generator could only emit
    ``azp == aud[0]``, and the verifier only accepted that same shape — so the
    pair was self-consistent but rejected every real IdP's tokens.
    """

    async def test_token_minted_with_an_explicit_client_azp_verifies(
        self,
        jwt_generate_service: Any,
        jwt_verify_service: JwtVerificationService,
        config: ConfigData,
        secret_for_jwt_generation: str,
        kid_for_jwt: str,
    ) -> None:
        with with_context(config_override=config):
            token = jwt_generate_service.generate_jwt(
                subject="keycloak-user-123",
                issuer=_ISSUER,
                audience=[_API_AUDIENCE, "account"],
                azp=_CLIENT_ID,
                secret=secret_for_jwt_generation,
                kid=kid_for_jwt,
            )

        claims = await _verify(jwt_verify_service, config, token)

        assert claims.subject == "keycloak-user-123"


class TestSingleAudienceAzpUnchanged:
    async def test_client_id_azp_verifies(
        self,
        jwt_verify_service: JwtVerificationService,
        config: ConfigData,
        secret_for_jwt_generation: str,
        kid_for_jwt: str,
    ) -> None:
        token = _mint(
            secret_for_jwt_generation, kid_for_jwt, aud=_API_AUDIENCE, azp=_CLIENT_ID
        )

        claims = await _verify(jwt_verify_service, config, token)

        assert claims.subject == "keycloak-user-123"

    async def test_unrelated_azp_is_rejected(
        self,
        jwt_verify_service: JwtVerificationService,
        config: ConfigData,
        secret_for_jwt_generation: str,
        kid_for_jwt: str,
    ) -> None:
        token = _mint(
            secret_for_jwt_generation,
            kid_for_jwt,
            aud=_API_AUDIENCE,
            azp="some-other-client",
        )

        with pytest.raises(HTTPException) as exc:
            await _verify(jwt_verify_service, config, token)

        assert exc.value.status_code == 401
        assert "Invalid azp for single-audience token" in exc.value.detail
