"""Health check endpoints router for monitoring service availability.

This module provides HTTP endpoints for health checking the application
and its dependencies. These endpoints are used by:

- Kubernetes liveness probes (/health)
- Kubernetes readiness probes (/health/ready)
- Monitoring systems
- Load balancers

Endpoint Summary:
    GET /health         - Liveness probe (app is running)
    GET /health/ready   - Readiness probe (all services operational)
    GET /health/database - Database-specific health check
    GET /health/redis   - Redis-specific health check
    GET /health/temporal - Temporal-specific health check
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse

from src.app.api.http.app_data import ApplicationDependencies
from src.app.api.http.schemas.health import (
    DatabaseHealthDetailed,
    HealthCheckError,
    LivenessResponse,
    OverallStatus,
    ReadinessResponse,
    RedisHealthDetailed,
    ServiceStatus,
    TemporalHealthDetailed,
)
from src.app.core.services.health_service import HealthCheckService
from src.app.runtime.context import get_config

router = APIRouter(prefix="/health", tags=["health"])


# =============================================================================
# Dependencies
# =============================================================================


def get_health_service(request: Request) -> HealthCheckService:
    """Get the health check service instance.

    This dependency creates a HealthCheckService with the application's
    dependencies and configuration.
    """
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    config = get_config()
    return HealthCheckService(app_deps, config)


# =============================================================================
# Liveness Probe
# =============================================================================


@router.get(
    "",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="Basic health check - returns 200 if the application process is running.",
)
async def health() -> LivenessResponse:
    """Basic health check endpoint - checks if app is running.

    This is a liveness probe that returns 200 OK as long as the application
    process is running. It does not check dependencies.

    Use this endpoint for Kubernetes liveness probes.
    """
    return LivenessResponse()


# =============================================================================
# Readiness Probe
# =============================================================================


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={
        200: {"description": "All services are ready"},
        503: {
            "description": "One or more services are not ready",
            "model": ReadinessResponse,
        },
    },
    summary="Readiness probe",
    description="Comprehensive readiness check - validates all service dependencies.",
)
async def readiness(
    health_service: HealthCheckService = Depends(get_health_service),
) -> ReadinessResponse | JSONResponse:
    """Comprehensive readiness check - validates all service dependencies.

    Returns 200 if all critical services are ready, 503 if any are unavailable.

    This checks:
    - Database connectivity (critical)
    - Redis connectivity (non-critical, falls back to in-memory)
    - Temporal connectivity (critical if enabled)
    - OIDC providers (critical in production only)

    Use this endpoint for Kubernetes readiness probes.
    """
    result = await health_service.check_all()

    if result.status == OverallStatus.NOT_READY:
        return JSONResponse(
            status_code=503,
            content=result.model_dump(mode="json"),
        )

    return result


# =============================================================================
# Individual Service Health Checks
# =============================================================================


@router.get(
    "/database",
    response_model=DatabaseHealthDetailed,
    responses={
        503: {
            "description": "Database is unhealthy",
            "model": HealthCheckError,
        },
    },
    summary="Database health check",
    description="Database-specific health check with connection pool status.",
)
async def health_database(request: Request) -> DatabaseHealthDetailed | JSONResponse:
    """Database-specific health check with connection pool status.

    Returns detailed information about the database connection including
    pool statistics when available.
    """
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    config = get_config()

    db_type = "postgresql" if "postgresql" in config.database.url else "sqlite"

    try:
        healthy = app_deps.database_service.health_check()
        pool_status = app_deps.database_service.get_pool_status()

        # Convert pool_status to compatible type
        pool: dict[str, int | str] | None = dict(pool_status) if pool_status else None

        return DatabaseHealthDetailed(
            status=ServiceStatus.HEALTHY if healthy else ServiceStatus.UNHEALTHY,
            type=db_type,
            pool=pool,
        )
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content=HealthCheckError(
                status=ServiceStatus.UNHEALTHY,
                error=str(e),
                error_type=type(e).__name__,
            ).model_dump(mode="json"),
        )


@router.get(
    "/redis",
    response_model=RedisHealthDetailed,
    responses={
        503: {
            "description": "Redis is unhealthy",
            "model": HealthCheckError,
        },
    },
    summary="Redis health check",
    description="Redis-specific health check with server information.",
)
async def health_redis(
    health_service: HealthCheckService = Depends(get_health_service),
) -> RedisHealthDetailed | JSONResponse:
    """Redis-specific health check using actual Redis operations.

    This performs a real test operation (set/get/delete) to verify
    Redis is functioning correctly, not just a simple PING.

    Returns detailed Redis server information when available.
    """
    result = await health_service.check_redis_detailed()

    if result.status == ServiceStatus.UNHEALTHY:
        return JSONResponse(
            status_code=503,
            content=result.model_dump(mode="json"),
        )

    return result


@router.get(
    "/temporal",
    response_model=TemporalHealthDetailed,
    responses={
        503: {
            "description": "Temporal is unhealthy",
            "model": HealthCheckError,
        },
    },
    summary="Temporal health check",
    description="Temporal workflow service health check.",
)
async def health_temporal(
    health_service: HealthCheckService = Depends(get_health_service),
) -> TemporalHealthDetailed | JSONResponse:
    """Temporal-specific health check.

    Returns connection status and configuration details for the
    Temporal workflow service.
    """
    result = await health_service.check_temporal_detailed()

    if result.status == ServiceStatus.UNHEALTHY:
        return JSONResponse(
            status_code=503,
            content=result.model_dump(mode="json"),
        )

    return result
