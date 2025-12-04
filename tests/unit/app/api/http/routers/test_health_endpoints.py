"""Unit tests for health check API endpoints.

These tests verify the health router behavior with mocked dependencies.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.api.http.routers.health import get_health_service, router
from src.app.api.http.schemas.health import (
    AllServicesHealth,
    DatabaseHealth,
    LivenessResponse,
    OverallStatus,
    ReadinessResponse,
    RedisHealth,
    RedisHealthDetailed,
    ServiceStatus,
    TemporalHealth,
    TemporalHealthDetailed,
)
from src.app.core.services.health_service import HealthCheckService


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock configuration."""
    config = MagicMock()
    config.app.environment = "development"
    config.database.url = "sqlite:///test.db"
    config.redis.enabled = True
    config.redis.url = "redis://localhost:6379"
    config.temporal.enabled = False
    config.oidc.providers = {}
    return config


@pytest.fixture
def mock_app_deps() -> MagicMock:
    """Create mock application dependencies."""
    deps = MagicMock()
    deps.database_service.health_check.return_value = True
    deps.database_service.get_pool_status.return_value = {"size": 5, "in_use": 1}
    deps.redis_service = AsyncMock()
    deps.redis_service.health_check = AsyncMock(return_value=True)
    deps.redis_service.get_info = AsyncMock(
        return_value={"version": "7.0.0", "connected_clients": 5}
    )
    deps.temporal_service.is_enabled = False
    deps.temporal_service.health_check = AsyncMock(return_value=True)
    deps.temporal_service.url = "localhost:7233"
    deps.temporal_service.namespace = "default"
    deps.temporal_service.task_queue = "app"
    deps.jwks_service = AsyncMock()
    return deps


@pytest.fixture
def mock_health_service(mock_app_deps: MagicMock, mock_config: MagicMock) -> MagicMock:
    """Create a mock health check service."""
    service = MagicMock(spec=HealthCheckService)

    # Configure check_all to return a successful response
    service.check_all = AsyncMock(
        return_value=ReadinessResponse(
            status=OverallStatus.READY,
            environment="development",
            checks=AllServicesHealth(
                database=DatabaseHealth(status=ServiceStatus.HEALTHY, type="sqlite"),
                redis=RedisHealth(status=ServiceStatus.DISABLED, type="in-memory"),
                temporal=TemporalHealth(status=ServiceStatus.DISABLED),
            ),
        )
    )

    service.check_redis_detailed = AsyncMock(
        return_value=RedisHealthDetailed(
            status=ServiceStatus.HEALTHY,
            type="redis",
            url="redis://localhost:6379",
            info={"version": "7.0.0"},
        )
    )

    service.check_temporal_detailed = AsyncMock(
        return_value=TemporalHealthDetailed(
            status=ServiceStatus.DISABLED,
            note="Temporal service is not enabled",
        )
    )

    return service


@pytest.fixture
def test_app(mock_health_service: MagicMock) -> FastAPI:
    """Create test FastAPI application."""
    app = FastAPI()
    app.include_router(router)

    # Override the health service dependency
    app.dependency_overrides[get_health_service] = lambda: mock_health_service

    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    """Create test client."""
    return TestClient(test_app)


class TestLivenessEndpoint:
    """Tests for the /health liveness probe endpoint."""

    def test_health_returns_healthy(self, client: TestClient) -> None:
        """Test basic health check returns healthy status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "api"

    def test_health_response_model(self, client: TestClient) -> None:
        """Test health response matches LivenessResponse model."""
        response = client.get("/health")
        data = response.json()

        # Validate against model
        liveness = LivenessResponse(**data)
        assert liveness.status == "healthy"
        assert liveness.service == "api"


class TestReadinessEndpoint:
    """Tests for the /health/ready readiness probe endpoint."""

    def test_readiness_returns_ready(
        self, client: TestClient, mock_health_service: MagicMock
    ) -> None:
        """Test readiness check returns ready when all services healthy."""
        response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["environment"] == "development"
        assert "checks" in data

    def test_readiness_returns_503_when_not_ready(
        self, client: TestClient, mock_health_service: MagicMock
    ) -> None:
        """Test readiness check returns 503 when critical services fail."""
        # Configure service to return NOT_READY
        mock_health_service.check_all = AsyncMock(
            return_value=ReadinessResponse(
                status=OverallStatus.NOT_READY,
                environment="development",
                checks=AllServicesHealth(
                    database=DatabaseHealth(
                        status=ServiceStatus.UNHEALTHY,
                        type="postgresql",
                        error="Connection refused",
                    ),
                    redis=RedisHealth(status=ServiceStatus.HEALTHY, type="redis"),
                    temporal=TemporalHealth(status=ServiceStatus.DISABLED),
                ),
            )
        )

        response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["checks"]["database"]["status"] == "unhealthy"

    def test_readiness_includes_all_service_checks(
        self, client: TestClient, mock_health_service: MagicMock
    ) -> None:
        """Test readiness response includes all expected service checks."""
        response = client.get("/health/ready")
        data = response.json()

        checks = data["checks"]
        assert "database" in checks
        assert "redis" in checks
        assert "temporal" in checks


class TestRedisHealthEndpoint:
    """Tests for the /health/redis endpoint."""

    def test_redis_healthy(
        self, client: TestClient, mock_health_service: MagicMock
    ) -> None:
        """Test Redis health check returns healthy status."""
        response = client.get("/health/redis")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["type"] == "redis"

    def test_redis_unhealthy_returns_503(
        self, client: TestClient, mock_health_service: MagicMock
    ) -> None:
        """Test Redis health check returns 503 when unhealthy."""
        mock_health_service.check_redis_detailed = AsyncMock(
            return_value=RedisHealthDetailed(
                status=ServiceStatus.UNHEALTHY,
                type="redis",
                error="Connection refused",
            )
        )

        response = client.get("/health/redis")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"

    def test_redis_disabled(
        self, client: TestClient, mock_health_service: MagicMock
    ) -> None:
        """Test Redis health check shows disabled status."""
        mock_health_service.check_redis_detailed = AsyncMock(
            return_value=RedisHealthDetailed(
                status=ServiceStatus.DISABLED,
                type="in-memory",
                note="Redis is not enabled, using in-memory storage",
            )
        )

        response = client.get("/health/redis")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disabled"
        assert data["type"] == "in-memory"


class TestTemporalHealthEndpoint:
    """Tests for the /health/temporal endpoint."""

    def test_temporal_disabled(
        self, client: TestClient, mock_health_service: MagicMock
    ) -> None:
        """Test Temporal health check shows disabled status."""
        response = client.get("/health/temporal")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disabled"

    def test_temporal_healthy(
        self, client: TestClient, mock_health_service: MagicMock
    ) -> None:
        """Test Temporal health check returns healthy when enabled."""
        mock_health_service.check_temporal_detailed = AsyncMock(
            return_value=TemporalHealthDetailed(
                status=ServiceStatus.HEALTHY,
                url="localhost:7233",
                namespace="default",
                task_queue="app",
            )
        )

        response = client.get("/health/temporal")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["url"] == "localhost:7233"

    def test_temporal_unhealthy_returns_503(
        self, client: TestClient, mock_health_service: MagicMock
    ) -> None:
        """Test Temporal health check returns 503 when unhealthy."""
        mock_health_service.check_temporal_detailed = AsyncMock(
            return_value=TemporalHealthDetailed(
                status=ServiceStatus.UNHEALTHY,
                error="Connection timeout",
            )
        )

        response = client.get("/health/temporal")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"


class TestServiceStatusEnum:
    """Tests for the ServiceStatus enum values."""

    def test_enum_values(self) -> None:
        """Test ServiceStatus enum has expected values."""
        assert ServiceStatus.HEALTHY.value == "healthy"
        assert ServiceStatus.UNHEALTHY.value == "unhealthy"
        assert ServiceStatus.DEGRADED.value == "degraded"
        assert ServiceStatus.DISABLED.value == "disabled"

    def test_enum_serialization(self) -> None:
        """Test ServiceStatus serializes correctly in Pydantic models."""
        health = DatabaseHealth(status=ServiceStatus.HEALTHY, type="sqlite")
        data = health.model_dump()

        # With use_enum_values=True, should serialize as string
        assert data["status"] == "healthy"
