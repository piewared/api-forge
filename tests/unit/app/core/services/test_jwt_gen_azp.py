"""Unit tests for authorized-party (azp) handling in ``generate_jwt``.

``azp`` names the client the token was issued to. The generator previously
force-set it to ``aud[0]`` for every multi-audience token, overwriting whatever
the caller supplied — so it could not emit a specification-shaped token at all,
and it mutated the caller's ``claims`` dict as a side effect.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from src.app.core.services import JwtGeneratorService
from src.app.runtime.config.config_data import ConfigData, JWTConfig
from src.app.runtime.context import with_context

_SECRET = "generator-secret-key"


def _claims_of(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


@pytest.fixture
def config() -> ConfigData:
    return ConfigData(jwt=JWTConfig(allowed_algorithms=["HS256"]))


@pytest.fixture
def generator() -> JwtGeneratorService:
    return JwtGeneratorService()


def _generate(
    generator: JwtGeneratorService, config: ConfigData, **kwargs: Any
) -> dict[str, Any]:
    with with_context(config_override=config):
        return _claims_of(generator.generate_jwt(secret=_SECRET, **kwargs))


class TestExplicitAzp:
    def test_explicit_azp_is_used_verbatim(
        self, generator: JwtGeneratorService, config: ConfigData
    ) -> None:
        """The regression: a caller-supplied azp must survive."""
        claims = _generate(
            generator,
            config,
            subject="user-1",
            audience=["api://default", "account"],
            azp="my-client",
        )

        assert claims["azp"] == "my-client"

    def test_explicit_azp_beats_a_value_in_claims(
        self, generator: JwtGeneratorService, config: ConfigData
    ) -> None:
        claims = _generate(
            generator,
            config,
            subject="user-1",
            audience=["api://default", "account"],
            azp="explicit-client",
            claims={"azp": "claims-client"},
        )

        assert claims["azp"] == "explicit-client"

    def test_azp_from_claims_is_honoured(
        self, generator: JwtGeneratorService, config: ConfigData
    ) -> None:
        """This is how the token helpers route azp via ``**extra_claims``."""
        claims = _generate(
            generator,
            config,
            subject="user-1",
            audience=["api://default", "account"],
            claims={"azp": "helper-client"},
        )

        assert claims["azp"] == "helper-client"

    def test_explicit_azp_applies_to_single_audience_tokens(
        self, generator: JwtGeneratorService, config: ConfigData
    ) -> None:
        claims = _generate(
            generator,
            config,
            subject="user-1",
            audience="api://default",
            azp="my-client",
        )

        assert claims["azp"] == "my-client"


class TestFallback:
    def test_multi_audience_without_azp_falls_back_to_primary_audience(
        self, generator: JwtGeneratorService, config: ConfigData
    ) -> None:
        """Compatibility default — OIDC wants azp present for multi-audience."""
        claims = _generate(
            generator,
            config,
            subject="user-1",
            audience=["api://default", "account"],
        )

        assert claims["azp"] == "api://default"

    def test_single_audience_without_azp_omits_the_claim(
        self, generator: JwtGeneratorService, config: ConfigData
    ) -> None:
        claims = _generate(
            generator, config, subject="user-1", audience="api://default"
        )

        assert "azp" not in claims


class TestNoCallerMutation:
    def test_claims_dict_is_not_modified(
        self, generator: JwtGeneratorService, config: ConfigData
    ) -> None:
        """The generator wrote azp into the caller's own dict."""
        caller_claims: dict[str, Any] = {"email": "user@example.com"}

        _generate(
            generator,
            config,
            subject="user-1",
            audience=["api://default", "account"],
            claims=caller_claims,
        )

        assert caller_claims == {"email": "user@example.com"}

    def test_other_custom_claims_still_pass_through(
        self, generator: JwtGeneratorService, config: ConfigData
    ) -> None:
        claims = _generate(
            generator,
            config,
            subject="user-1",
            audience=["api://default", "account"],
            azp="my-client",
            claims={"email": "user@example.com", "roles": ["admin"]},
        )

        assert claims["email"] == "user@example.com"
        assert claims["roles"] == ["admin"]
        assert claims["azp"] == "my-client"


class TestHelpersCanSetAzp:
    def test_access_token_accepts_azp_via_extra_claims(
        self, generator: JwtGeneratorService, config: ConfigData
    ) -> None:
        with with_context(config_override=config):
            token = generator.generate_access_token(
                user_id="user-1",
                audience=["api://default", "account"],
                secret=_SECRET,
                azp="my-client",
            )

        assert _claims_of(token)["azp"] == "my-client"
