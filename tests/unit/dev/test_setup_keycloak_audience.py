"""Unit tests for dev-realm audience alignment.

The dev Keycloak realm must mint access tokens whose ``aud`` claim the API
accepts, otherwise the Bearer-JWT path cannot be exercised locally at all.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.dev.setup_keycloak import (
    AUDIENCE_MAPPER_NAME,
    DEFAULT_API_AUDIENCE,
    KeycloakSetup,
    build_audience_mapper,
    get_api_audience,
)


class TestGetApiAudience:
    def test_defaults_to_the_config_yaml_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Must match config.yaml's "${JWT_AUDIENCE:-api://default}"."""
        monkeypatch.delenv("JWT_AUDIENCE", raising=False)

        assert get_api_audience() == DEFAULT_API_AUDIENCE == "api://default"

    def test_follows_the_jwt_audience_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JWT_AUDIENCE", "api://custom")

        assert get_api_audience() == "api://custom"

    def test_empty_override_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unset-but-present env var must not produce an empty audience."""
        monkeypatch.setenv("JWT_AUDIENCE", "")

        assert get_api_audience() == DEFAULT_API_AUDIENCE


class TestBuildAudienceMapper:
    def test_stamps_the_audience_into_the_access_token(self) -> None:
        mapper = build_audience_mapper("api://default")

        assert mapper["protocolMapper"] == "oidc-audience-mapper"
        assert mapper["config"]["included.custom.audience"] == "api://default"
        assert mapper["config"]["access.token.claim"] == "true"


class TestEnsureAudienceMapper:
    @pytest.fixture
    def setup(self, monkeypatch: pytest.MonkeyPatch) -> KeycloakSetup:
        monkeypatch.delenv("JWT_AUDIENCE", raising=False)
        instance = KeycloakSetup()
        instance.client = MagicMock()
        instance.client.get_client_by_id.return_value = {"id": "client-uuid"}
        return instance

    def test_creates_the_mapper_when_absent(self, setup: KeycloakSetup) -> None:
        client = setup.client
        client.get_protocol_mappers.return_value = []  # type: ignore[attr-defined]
        client.create_protocol_mapper.return_value = True  # type: ignore[attr-defined]

        setup.ensure_audience_mapper()

        client.create_protocol_mapper.assert_called_once()  # type: ignore[attr-defined]
        _realm, uuid, mapper = client.create_protocol_mapper.call_args[0]  # type: ignore[attr-defined]
        assert uuid == "client-uuid"
        assert mapper["config"]["included.custom.audience"] == DEFAULT_API_AUDIENCE

    def test_is_idempotent_when_already_present(self, setup: KeycloakSetup) -> None:
        client = setup.client
        client.get_protocol_mappers.return_value = [  # type: ignore[attr-defined]
            {"name": AUDIENCE_MAPPER_NAME}
        ]

        setup.ensure_audience_mapper()

        client.create_protocol_mapper.assert_not_called()  # type: ignore[attr-defined]

    def test_repairs_a_preexisting_client(self, setup: KeycloakSetup) -> None:
        """Realms seeded before the mapper existed must be fixed in place.

        ``create_client`` returns early for an existing client, so mapper
        creation cannot live inside it.
        """
        client = setup.client
        client.get_protocol_mappers.return_value = [  # type: ignore[attr-defined]
            {"name": "some-other-mapper"}
        ]
        client.create_protocol_mapper.return_value = True  # type: ignore[attr-defined]

        setup.ensure_audience_mapper()

        client.create_protocol_mapper.assert_called_once()  # type: ignore[attr-defined]

    def test_does_nothing_when_the_client_is_missing(
        self, setup: KeycloakSetup
    ) -> None:
        client = setup.client
        client.get_client_by_id.return_value = None  # type: ignore[attr-defined]

        setup.ensure_audience_mapper()

        client.create_protocol_mapper.assert_not_called()  # type: ignore[attr-defined]

    def test_uses_the_jwt_audience_override(
        self, setup: KeycloakSetup, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JWT_AUDIENCE", "api://staging")
        client = setup.client
        client.get_protocol_mappers.return_value = []  # type: ignore[attr-defined]
        client.create_protocol_mapper.return_value = True  # type: ignore[attr-defined]

        setup.ensure_audience_mapper()

        mapper: dict[str, Any] = client.create_protocol_mapper.call_args[0][2]  # type: ignore[attr-defined]
        assert mapper["config"]["included.custom.audience"] == "api://staging"
