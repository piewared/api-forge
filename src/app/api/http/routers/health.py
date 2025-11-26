"""Health check endpoints router for monitoring service availability."""

from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from src.app.api.http.app_data import ApplicationDependencies
from src.app.runtime.context import get_config

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health() -> dict[str, str]:
    """Basic health check endpoint - checks if app is running.

    This is a liveness probe that returns 200 OK as long as the application
    process is running. It does not check dependencies.
    """
    return {"status": "healthy", "service": "api"}


@router.get("/ready", response_model=None)
async def readiness(request: Request) -> dict[str, Any] | JSONResponse:
    """Comprehensive readiness check - validates all service dependencies.

    Returns 200 if all services are ready, 503 if any service is unavailable.

    This checks:
    - Database connectivity
    - Redis (non-critical, falls back to in-memory)
    - Temporal (if enabled)
    - OIDC providers (critical in production only)
    """
    from pydantic import BaseModel

    # Simple model for health check test data
    class HealthCheckData(BaseModel):
        test: bool

    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    config = get_config()

    checks: dict[str, Any] = {}
    all_healthy = True

    # Database health check
    try:
        db_healthy = app_deps.database_service.health_check()
        checks["database"] = {
            "status": "healthy" if db_healthy else "unhealthy",
            "type": "postgresql" if "postgresql" in config.database.url else "sqlite",
        }
        if not db_healthy:
            all_healthy = False
    except Exception as e:
        checks["database"] = {
            "status": "unhealthy",
            "error": str(e),
        }
        all_healthy = False

    # Redis health check
    try:
        if app_deps.redis_service:
            redis_healthy = await app_deps.redis_service.health_check()
        else:
            redis_healthy = False # Redis service not configured

        checks["redis"] = {
            "status": "healthy" if redis_healthy else "unhealthy" if config.redis.enabled else "degraded",
            "type": "redis" if config.redis.enabled else "in-memory",
        }
        # Redis failure is not critical - we fall back to in-memory
        # So we don't set all_healthy = False here
    except Exception as e:
        checks["redis"] = {
            "status": "degraded",
            "type": "in-memory",
            "note": "Using in-memory storage",
            "error": str(e) if config.redis.enabled else "Redis not configured",
        }
        # Redis failure is not critical - we fall back to in-memory

    # Temporal health check
    if config.temporal.enabled:
        try:
            temporal_healthy = await app_deps.temporal_service.health_check()
            checks["temporal"] = {
                "status": "healthy" if temporal_healthy else "unhealthy",
                "url": app_deps.temporal_service.url,
                "namespace": app_deps.temporal_service.namespace,
            }
            if not temporal_healthy:
                all_healthy = False
        except Exception as e:
            checks["temporal"] = {
                "status": "unhealthy",
                "error": str(e),
            }
            all_healthy = False
    else:
        checks["temporal"] = {
            "status": "disabled",
            "note": "Temporal service is not enabled",
        }

    # OIDC providers check (verify JWKS endpoints are reachable)
    oidc_checks = {}
    if config.oidc.providers:
        jwks_service = app_deps.jwks_service
        for provider_name, provider_config in config.oidc.providers.items():
            try:
                # Try to fetch JWKS to verify provider is reachable
                _ = await jwks_service.fetch_jwks(provider_config)
                oidc_checks[provider_name] = {
                    "status": "healthy",
                    "issuer": provider_config.issuer,
                }
            except Exception as e:
                oidc_checks[provider_name] = {
                    "status": "unhealthy",
                    "issuer": provider_config.issuer,
                    "error": str(e),
                }
                # OIDC failures are not critical for non-production
                if config.app.environment == "production":
                    all_healthy = False

    if oidc_checks:
        checks["oidc_providers"] = oidc_checks

    # Build response
    response = {
        "status": "ready" if all_healthy else "not_ready",
        "environment": config.app.environment,
        "checks": checks,
    }

    # Return 503 if not all services are healthy
    if not all_healthy:
        return JSONResponse(
            status_code=503,
            content=response,
        )

    return response


@router.get("/database", response_model=None)
async def health_database(request: Request) -> dict[str, Any] | JSONResponse:
    """Database-specific health check with connection pool status."""
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    config = get_config()

    try:
        healthy = app_deps.database_service.health_check()
        pool_status = app_deps.database_service.get_pool_status()

        return {
            "status": "healthy" if healthy else "unhealthy",
            "type": "postgresql" if "postgresql" in config.database.url else "sqlite",
            "pool": pool_status,
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )


@router.get("/redis", response_model=None)
async def health_redis(request: Request) -> dict[str, Any] | JSONResponse:
    """Redis-specific health check using actual Redis operations.

    This performs a real test operation (set/get/delete) to verify
    Redis is functioning correctly, not just a simple PING.
    """
    app_deps: ApplicationDependencies = request.app.state.app_dependencies
    config = get_config()

    if not config.redis.enabled:
        return {
            "status": "disabled",
            "type": "in-memory",
            "note": "Redis is not enabled, using in-memory storage",
        }

    try:
        # Use the health_check method from RedisService
        if app_deps.redis_service:
            healthy = await app_deps.redis_service.health_check()
            # Optionally get more detailed info
            info = await app_deps.redis_service.get_info()
        else:
            healthy = False # Redis service not configured
            info = None

        result: dict[str, Any] = {
            "status": "healthy" if healthy else "unhealthy",
            "type": "redis",
            "url": config.redis.url,
        }

        if info:
            result["info"] = info

        return result
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "type": "redis",
                "error": str(e),
                "error_type": type(e).__name__,
                "fallback": "in-memory storage",
            },
        )


@router.get("/temporal", response_model=None)
async def health_temporal(request: Request) -> dict[str, Any] | JSONResponse:
    """Temporal-specific health check."""
    app_deps: ApplicationDependencies = request.app.state.app_dependencies

    if not app_deps.temporal_service.is_enabled:
        return {
            "status": "disabled",
            "note": "Temporal service is not enabled",
        }

    try:
        healthy = await app_deps.temporal_service.health_check()

        return {
            "status": "healthy" if healthy else "unhealthy",
            "url": app_deps.temporal_service.url,
            "namespace": app_deps.temporal_service.namespace,
            "task_queue": app_deps.temporal_service.task_queue,
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
