"""Health check response schemas.

This module defines the Pydantic models for health check API responses,
providing a consistent and well-documented interface for health endpoints.

Status Terminology:
    - healthy: Service is fully operational
    - unhealthy: Service is not operational (critical failure)
    - degraded: Service is partially operational or using fallback
    - disabled: Service is intentionally not enabled in configuration
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ServiceStatus(str, Enum):
    """Standard status values for service health checks.

    These statuses provide a consistent vocabulary across all health
    check responses:

    - HEALTHY: Service is fully operational and responding normally
    - UNHEALTHY: Service is not operational (connection failed, errors, etc.)
    - DEGRADED: Service is partially operational or using a fallback mechanism
    - DISABLED: Service is intentionally not enabled in the configuration
    """

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    DISABLED = "disabled"


class OverallStatus(str, Enum):
    """Overall application readiness status.

    - READY: All critical services are operational
    - NOT_READY: One or more critical services are not operational
    """

    READY = "ready"
    NOT_READY = "not_ready"


# =============================================================================
# Base Models
# =============================================================================


class ServiceHealthBase(BaseModel):
    """Base model for individual service health check results."""

    model_config = ConfigDict(use_enum_values=True)

    status: ServiceStatus = Field(description="Current health status of the service")
    note: str | None = Field(
        default=None,
        description="Optional additional context about the status",
    )
    error: str | None = Field(
        default=None,
        description="Error message if status is unhealthy",
    )


# =============================================================================
# Database Health Models
# =============================================================================


class DatabaseHealth(ServiceHealthBase):
    """Health check result for the database service."""

    type: Annotated[
        str,
        Field(description="Database type (postgresql, sqlite)"),
    ]


class DatabaseHealthDetailed(DatabaseHealth):
    """Detailed health check result for the database with pool info."""

    pool: dict[str, int | str] | None = Field(
        default=None,
        description="Connection pool statistics",
    )


# =============================================================================
# Redis Health Models
# =============================================================================


class RedisHealth(ServiceHealthBase):
    """Health check result for the Redis service."""

    type: Annotated[
        str,
        Field(description="Storage type (redis, in-memory)"),
    ]


class RedisHealthDetailed(RedisHealth):
    """Detailed health check result for Redis with server info."""

    url: str | None = Field(
        default=None,
        description="Redis connection URL (masked)",
    )
    info: dict[str, str | int] | None = Field(
        default=None,
        description="Redis server information",
    )
    fallback: str | None = Field(
        default=None,
        description="Fallback mechanism being used if Redis is unavailable",
    )


# =============================================================================
# Temporal Health Models
# =============================================================================


class TemporalHealth(ServiceHealthBase):
    """Health check result for the Temporal workflow service."""

    url: str | None = Field(
        default=None,
        description="Temporal server URL",
    )
    namespace: str | None = Field(
        default=None,
        description="Temporal namespace",
    )


class TemporalHealthDetailed(TemporalHealth):
    """Detailed health check result for Temporal."""

    task_queue: str | None = Field(
        default=None,
        description="Temporal task queue name",
    )


# =============================================================================
# OIDC Provider Health Models
# =============================================================================


class OIDCProviderHealth(ServiceHealthBase):
    """Health check result for an individual OIDC provider."""

    issuer: str = Field(description="OIDC issuer URL")


class OIDCProvidersHealth(BaseModel):
    """Health check results for all configured OIDC providers."""

    model_config = ConfigDict(extra="allow")

    # Dynamic fields for each provider (e.g., google, microsoft, keycloak)
    # Using extra="allow" to handle dynamic provider names


# =============================================================================
# Aggregate Health Check Models
# =============================================================================


class AllServicesHealth(BaseModel):
    """Aggregated health check results for all services."""

    model_config = ConfigDict(use_enum_values=True)

    database: DatabaseHealth
    redis: RedisHealth
    temporal: TemporalHealth
    oidc_providers: dict[str, OIDCProviderHealth] | None = Field(
        default=None,
        description="Health status of configured OIDC providers",
    )


class ReadinessResponse(BaseModel):
    """Response model for the /health/ready endpoint.

    This is the primary health check endpoint used by Kubernetes
    readiness probes to determine if the application is ready
    to receive traffic.
    """

    model_config = ConfigDict(use_enum_values=True)

    status: OverallStatus = Field(description="Overall application readiness status")
    environment: str = Field(
        description="Current deployment environment (development, production, etc.)"
    )
    checks: AllServicesHealth = Field(
        description="Individual service health check results"
    )


class LivenessResponse(BaseModel):
    """Response model for the /health endpoint (liveness probe).

    This is a simple health check that only verifies the application
    process is running. It does not check dependencies.
    """

    status: Annotated[
        str,
        Field(description="Always 'healthy' if the app is running"),
    ] = "healthy"
    service: Annotated[
        str,
        Field(description="Service identifier"),
    ] = "api"


# =============================================================================
# Error Response Models
# =============================================================================


class HealthCheckError(BaseModel):
    """Error response for health check endpoints."""

    status: ServiceStatus = ServiceStatus.UNHEALTHY
    error: str = Field(description="Error message")
    error_type: str = Field(description="Exception class name")
