"""Unit tests for the HealthCheckService.

These tests verify the health check service logic with mocked dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.api.http.schemas.health import (
    OverallStatus,
    ServiceStatus,
)
from src.app.core.services.health_service import HealthCheckService

if TYPE_CHECKING:
    pass


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock configuration."""
    config = MagicMock()
    config.app.environment = "development"
    config.database.url = "postgresql://localhost:5432/test"
    config.redis.enabled = True
    config.redis.url = "redis://localhost:6379"
    config.temporal.enabled = True
    config.oidc.providers = {}
    return config


@pytest.fixture
def mock_app_deps() -> MagicMock:
    """Create mock application dependencies."""
    deps = MagicMock()

    # Database service mocks
    deps.database_service.health_check.return_value = True
    deps.database_service.get_pool_status.return_value = {"size": 5, "in_use": 1}

    # Redis service mocks
    deps.redis_service = AsyncMock()
    deps.redis_service.health_check = AsyncMock(return_value=True)
    deps.redis_service.get_info = AsyncMock(
        return_value={"version": "7.0.0", "connected_clients": 5}
    )

    # Temporal service mocks
    deps.temporal_service = MagicMock()
    deps.temporal_service.health_check = AsyncMock(return_value=True)
    deps.temporal_service.url = "localhost:7233"
    deps.temporal_service.namespace = "default"
    deps.temporal_service.task_queue = "app"

    # JWKS service for OIDC checks
    deps.jwks_service = AsyncMock()

    return deps


@pytest.fixture
def health_service(
    mock_app_deps: MagicMock, mock_config: MagicMock
) -> HealthCheckService:
    """Create a HealthCheckService instance with mocked dependencies."""
    return HealthCheckService(mock_app_deps, mock_config)


class TestCheckAll:
    """Tests for the check_all method."""

    async def test_all_services_healthy(
        self, health_service: HealthCheckService
    ) -> None:
        """Test check_all returns READY when all services are healthy."""
        result = await health_service.check_all()

        assert result.status == OverallStatus.READY
        assert result.checks.database.status == ServiceStatus.HEALTHY
        assert result.checks.redis.status == ServiceStatus.HEALTHY
        assert result.checks.temporal.status == ServiceStatus.HEALTHY

    async def test_database_failure_makes_not_ready(
        self,
        mock_app_deps: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test check_all returns NOT_READY when database fails."""
        mock_app_deps.database_service.health_check.return_value = False
        service = HealthCheckService(mock_app_deps, mock_config)

        result = await service.check_all()

        assert result.status == OverallStatus.NOT_READY
        assert result.checks.database.status == ServiceStatus.UNHEALTHY

    async def test_redis_failure_still_ready(
        self,
        mock_app_deps: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test check_all returns READY even when Redis fails (non-critical)."""
        mock_app_deps.redis_service.health_check = AsyncMock(return_value=False)
        service = HealthCheckService(mock_app_deps, mock_config)

        result = await service.check_all()

        # Redis is non-critical, so should still be READY
        assert result.status == OverallStatus.READY
        assert result.checks.redis.status == ServiceStatus.DEGRADED

    async def test_temporal_failure_makes_not_ready(
        self,
        mock_app_deps: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test check_all returns NOT_READY when Temporal fails (if enabled)."""
        mock_app_deps.temporal_service.health_check = AsyncMock(return_value=False)
        service = HealthCheckService(mock_app_deps, mock_config)

        result = await service.check_all()

        assert result.status == OverallStatus.NOT_READY
        assert result.checks.temporal.status == ServiceStatus.UNHEALTHY


class TestCheckDatabase:
    """Tests for the check_database method."""

    async def test_healthy_postgresql(self, health_service: HealthCheckService) -> None:
        """Test database check returns healthy for PostgreSQL."""
        result = await health_service.check_database()

        assert result.status == ServiceStatus.HEALTHY
        assert result.type == "postgresql"
        assert result.error is None

    async def test_healthy_sqlite(
        self, mock_app_deps: MagicMock, mock_config: MagicMock
    ) -> None:
        """Test database check returns healthy for SQLite."""
        mock_config.database.url = "sqlite:///test.db"
        service = HealthCheckService(mock_app_deps, mock_config)

        result = await service.check_database()

        assert result.status == ServiceStatus.HEALTHY
        assert result.type == "sqlite"

    async def test_database_exception(
        self, mock_app_deps: MagicMock, mock_config: MagicMock
    ) -> None:
        """Test database check returns unhealthy on exception."""
        mock_app_deps.database_service.health_check.side_effect = Exception(
            "Connection refused"
        )
        service = HealthCheckService(mock_app_deps, mock_config)

        result = await service.check_database()

        assert result.status == ServiceStatus.UNHEALTHY
        assert result.error == "Connection refused"


class TestCheckRedis:
    """Tests for the check_redis method."""

    async def test_redis_healthy(self, health_service: HealthCheckService) -> None:
        """Test Redis check returns healthy when working."""
        result = await health_service.check_redis()

        assert result.status == ServiceStatus.HEALTHY
        assert result.type == "redis"

    async def test_redis_disabled(
        self, mock_app_deps: MagicMock, mock_config: MagicMock
    ) -> None:
        """Test Redis check returns disabled when not enabled."""
        mock_config.redis.enabled = False
        service = HealthCheckService(mock_app_deps, mock_config)

        result = await service.check_redis()

        assert result.status == ServiceStatus.DISABLED
        assert result.type == "in-memory"
        assert "not enabled" in (result.note or "")

    async def test_redis_service_not_initialized(
        self, mock_app_deps: MagicMock, mock_config: MagicMock
    ) -> None:
        """Test Redis check returns degraded when service not initialized."""
        mock_app_deps.redis_service = None
        service = HealthCheckService(mock_app_deps, mock_config)

        result = await service.check_redis()

        assert result.status == ServiceStatus.DEGRADED
        assert result.type == "in-memory"

    async def test_redis_exception(
        self, mock_app_deps: MagicMock, mock_config: MagicMock
    ) -> None:
        """Test Redis check returns degraded on exception."""
        mock_app_deps.redis_service.health_check = AsyncMock(
            side_effect=Exception("Connection timeout")
        )
        service = HealthCheckService(mock_app_deps, mock_config)

        result = await service.check_redis()

        assert result.status == ServiceStatus.DEGRADED
        assert "Connection timeout" in (result.error or "")


class TestCheckTemporal:
    """Tests for the check_temporal method."""

    async def test_temporal_healthy(self, health_service: HealthCheckService) -> None:
        """Test Temporal check returns healthy when working."""
        result = await health_service.check_temporal()

        assert result.status == ServiceStatus.HEALTHY
        assert result.url == "localhost:7233"
        assert result.namespace == "default"

    async def test_temporal_disabled(
        self, mock_app_deps: MagicMock, mock_config: MagicMock
    ) -> None:
        """Test Temporal check returns disabled when not enabled."""
        mock_config.temporal.enabled = False
        service = HealthCheckService(mock_app_deps, mock_config)

        result = await service.check_temporal()

        assert result.status == ServiceStatus.DISABLED
        assert "not enabled" in (result.note or "")

    async def test_temporal_exception(
        self, mock_app_deps: MagicMock, mock_config: MagicMock
    ) -> None:
        """Test Temporal check returns unhealthy on exception."""
        mock_app_deps.temporal_service.health_check = AsyncMock(
            side_effect=Exception("Service unavailable")
        )
        service = HealthCheckService(mock_app_deps, mock_config)

        result = await service.check_temporal()

        assert result.status == ServiceStatus.UNHEALTHY
        assert "Service unavailable" in (result.error or "")


class TestCheckTemporalDetailed:
    """Tests for the check_temporal_detailed method."""

    async def test_includes_task_queue(
        self, health_service: HealthCheckService
    ) -> None:
        """Test detailed Temporal check includes task queue."""
        result = await health_service.check_temporal_detailed()

        assert result.status == ServiceStatus.HEALTHY
        assert result.task_queue == "app"


class TestCheckRedisDetailed:
    """Tests for the check_redis_detailed method."""

    async def test_includes_server_info(
        self, health_service: HealthCheckService
    ) -> None:
        """Test detailed Redis check includes server info."""
        result = await health_service.check_redis_detailed()

        assert result.status == ServiceStatus.HEALTHY
        assert result.info is not None
        assert result.info.get("version") == "7.0.0"


class TestCheckOIDCProviders:
    """Tests for the check_oidc_providers method."""

    async def test_no_providers_configured(
        self, health_service: HealthCheckService
    ) -> None:
        """Test OIDC check returns None when no providers configured."""
        result = await health_service.check_oidc_providers()

        assert result is None

    async def test_provider_healthy(
        self, mock_app_deps: MagicMock, mock_config: MagicMock
    ) -> None:
        """Test OIDC check returns healthy for working provider."""
        # Add a mock provider
        mock_provider = MagicMock()
        mock_provider.issuer = "https://accounts.google.com"
        mock_config.oidc.providers = {"google": mock_provider}

        mock_app_deps.jwks_service.fetch_jwks = AsyncMock(return_value={})

        service = HealthCheckService(mock_app_deps, mock_config)
        result = await service.check_oidc_providers()

        assert result is not None
        assert "google" in result
        assert result["google"].status == ServiceStatus.HEALTHY
        assert result["google"].issuer == "https://accounts.google.com"

    async def test_provider_unhealthy(
        self, mock_app_deps: MagicMock, mock_config: MagicMock
    ) -> None:
        """Test OIDC check returns unhealthy for failing provider."""
        # Add a mock provider
        mock_provider = MagicMock()
        mock_provider.issuer = "https://accounts.google.com"
        mock_config.oidc.providers = {"google": mock_provider}

        mock_app_deps.jwks_service.fetch_jwks = AsyncMock(
            side_effect=Exception("JWKS fetch failed")
        )

        service = HealthCheckService(mock_app_deps, mock_config)
        result = await service.check_oidc_providers()

        assert result is not None
        assert "google" in result
        assert result["google"].status == ServiceStatus.UNHEALTHY
        assert "JWKS fetch failed" in (result["google"].error or "")


class TestOverallHealthEvaluation:
    """Tests for the _evaluate_overall_health method."""

    async def test_oidc_failure_critical_in_production(
        self, mock_app_deps: MagicMock, mock_config: MagicMock
    ) -> None:
        """Test OIDC failure makes app NOT_READY in production."""
        mock_config.app.environment = "production"

        # Add a failing OIDC provider
        mock_provider = MagicMock()
        mock_provider.issuer = "https://accounts.google.com"
        mock_config.oidc.providers = {"google": mock_provider}

        mock_app_deps.jwks_service.fetch_jwks = AsyncMock(
            side_effect=Exception("JWKS fetch failed")
        )

        service = HealthCheckService(mock_app_deps, mock_config)
        result = await service.check_all()

        assert result.status == OverallStatus.NOT_READY

    async def test_oidc_failure_not_critical_in_development(
        self, mock_app_deps: MagicMock, mock_config: MagicMock
    ) -> None:
        """Test OIDC failure doesn't make app NOT_READY in development."""
        mock_config.app.environment = "development"

        # Add a failing OIDC provider
        mock_provider = MagicMock()
        mock_provider.issuer = "https://accounts.google.com"
        mock_config.oidc.providers = {"google": mock_provider}

        mock_app_deps.jwks_service.fetch_jwks = AsyncMock(
            side_effect=Exception("JWKS fetch failed")
        )

        service = HealthCheckService(mock_app_deps, mock_config)
        result = await service.check_all()

        # In development, OIDC failures are not critical
        assert result.status == OverallStatus.READY
