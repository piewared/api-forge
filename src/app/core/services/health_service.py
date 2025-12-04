"""Health check service for application dependencies.

This module provides a centralized service for performing health checks
on all application dependencies (database, Redis, Temporal, OIDC providers).

The service abstracts health check logic from the HTTP layer, making it
testable and reusable across different contexts (HTTP endpoints, CLI tools,
background workers, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.app.api.http.schemas.health import (
    AllServicesHealth,
    DatabaseHealth,
    OIDCProviderHealth,
    OverallStatus,
    ReadinessResponse,
    RedisHealth,
    RedisHealthDetailed,
    ServiceStatus,
    TemporalHealth,
    TemporalHealthDetailed,
)

if TYPE_CHECKING:
    from src.app.api.http.app_data import ApplicationDependencies
    from src.app.runtime.config.config_data import ConfigData


@dataclass
class HealthCheckResult:
    """Result of an individual health check.

    Attributes:
        status: The health status of the service
        details: Additional details about the check (type, url, etc.)
        is_critical: Whether this service failure should mark the app as not ready
    """

    status: ServiceStatus
    details: dict[str, str | int | bool | None]
    is_critical: bool = True


class HealthCheckService:
    """Service for performing health checks on application dependencies.

    This service encapsulates all health check logic and provides a clean
    interface for checking individual services or all services at once.

    Example:
        ```python
        health_service = HealthCheckService(app_deps, config)
        result = await health_service.check_all()
        if result.status == OverallStatus.READY:
            print("All systems go!")
        ```
    """

    def __init__(
        self,
        app_deps: ApplicationDependencies,
        config: ConfigData,
    ) -> None:
        """Initialize the health check service.

        Args:
            app_deps: Application dependencies container
            config: Application configuration
        """
        self._app_deps = app_deps
        self._config = config

    # =========================================================================
    # Public API
    # =========================================================================

    async def check_all(self) -> ReadinessResponse:
        """Perform health checks on all services.

        Returns:
            ReadinessResponse with status of all services
        """
        database = await self.check_database()
        redis = await self.check_redis()
        temporal = await self.check_temporal()
        oidc_providers = await self.check_oidc_providers()

        # Determine overall status based on critical services
        all_healthy = self._evaluate_overall_health(
            database=database,
            redis=redis,
            temporal=temporal,
            oidc_providers=oidc_providers,
        )

        return ReadinessResponse(
            status=OverallStatus.READY if all_healthy else OverallStatus.NOT_READY,
            environment=self._config.app.environment,
            checks=AllServicesHealth(
                database=database,
                redis=redis,
                temporal=temporal,
                oidc_providers=oidc_providers if oidc_providers else None,
            ),
        )

    async def check_database(self) -> DatabaseHealth:
        """Check database connectivity.

        Returns:
            DatabaseHealth with status and database type
        """
        db_type = self._get_database_type()

        try:
            healthy = self._app_deps.database_service.health_check()
            return DatabaseHealth(
                status=ServiceStatus.HEALTHY if healthy else ServiceStatus.UNHEALTHY,
                type=db_type,
            )
        except Exception as e:
            return DatabaseHealth(
                status=ServiceStatus.UNHEALTHY,
                type=db_type,
                error=str(e),
            )

    async def check_redis(self) -> RedisHealth:
        """Check Redis connectivity.

        Redis is a non-critical service - if unavailable, the application
        falls back to in-memory storage.

        Returns:
            RedisHealth with status and storage type
        """
        if not self._config.redis.enabled:
            return RedisHealth(
                status=ServiceStatus.DISABLED,
                type="in-memory",
                note="Redis is not enabled, using in-memory storage",
            )

        try:
            if self._app_deps.redis_service:
                healthy = await self._app_deps.redis_service.health_check()
                return RedisHealth(
                    status=ServiceStatus.HEALTHY if healthy else ServiceStatus.DEGRADED,
                    type="redis" if healthy else "in-memory",
                    note=None if healthy else "Falling back to in-memory storage",
                )
            else:
                return RedisHealth(
                    status=ServiceStatus.DEGRADED,
                    type="in-memory",
                    note="Redis service not initialized, using in-memory storage",
                )
        except Exception as e:
            return RedisHealth(
                status=ServiceStatus.DEGRADED,
                type="in-memory",
                note="Using in-memory storage due to Redis error",
                error=str(e),
            )

    async def check_redis_detailed(self) -> RedisHealthDetailed:
        """Check Redis with detailed server information.

        Returns:
            RedisHealthDetailed with server info if available
        """
        if not self._config.redis.enabled:
            return RedisHealthDetailed(
                status=ServiceStatus.DISABLED,
                type="in-memory",
                note="Redis is not enabled, using in-memory storage",
            )

        try:
            if self._app_deps.redis_service:
                healthy = await self._app_deps.redis_service.health_check()
                info = (
                    await self._app_deps.redis_service.get_info() if healthy else None
                )

                return RedisHealthDetailed(
                    status=ServiceStatus.HEALTHY
                    if healthy
                    else ServiceStatus.UNHEALTHY,
                    type="redis",
                    url=self._config.redis.url,
                    info=info,
                )
            else:
                return RedisHealthDetailed(
                    status=ServiceStatus.DEGRADED,
                    type="in-memory",
                    note="Redis service not initialized",
                    fallback="in-memory storage",
                )
        except Exception as e:
            return RedisHealthDetailed(
                status=ServiceStatus.UNHEALTHY,
                type="redis",
                error=str(e),
                fallback="in-memory storage",
            )

    async def check_temporal(self) -> TemporalHealth:
        """Check Temporal workflow service connectivity.

        Returns:
            TemporalHealth with status and connection details
        """
        if not self._config.temporal.enabled:
            return TemporalHealth(
                status=ServiceStatus.DISABLED,
                note="Temporal service is not enabled",
            )

        try:
            healthy = await self._app_deps.temporal_service.health_check()
            return TemporalHealth(
                status=ServiceStatus.HEALTHY if healthy else ServiceStatus.UNHEALTHY,
                url=self._app_deps.temporal_service.url,
                namespace=self._app_deps.temporal_service.namespace,
            )
        except Exception as e:
            return TemporalHealth(
                status=ServiceStatus.UNHEALTHY,
                error=str(e),
            )

    async def check_temporal_detailed(self) -> TemporalHealthDetailed:
        """Check Temporal with detailed configuration info.

        Returns:
            TemporalHealthDetailed with task queue info
        """
        if not self._config.temporal.enabled:
            return TemporalHealthDetailed(
                status=ServiceStatus.DISABLED,
                note="Temporal service is not enabled",
            )

        try:
            healthy = await self._app_deps.temporal_service.health_check()
            return TemporalHealthDetailed(
                status=ServiceStatus.HEALTHY if healthy else ServiceStatus.UNHEALTHY,
                url=self._app_deps.temporal_service.url,
                namespace=self._app_deps.temporal_service.namespace,
                task_queue=self._app_deps.temporal_service.task_queue,
            )
        except Exception as e:
            return TemporalHealthDetailed(
                status=ServiceStatus.UNHEALTHY,
                error=str(e),
            )

    async def check_oidc_providers(self) -> dict[str, OIDCProviderHealth] | None:
        """Check all configured OIDC providers.

        Returns:
            Dict of provider name to health status, or None if no providers configured
        """
        if not self._config.oidc.providers:
            return None

        results: dict[str, OIDCProviderHealth] = {}
        jwks_service = self._app_deps.jwks_service

        for provider_name, provider_config in self._config.oidc.providers.items():
            try:
                # Verify provider is reachable by fetching JWKS
                await jwks_service.fetch_jwks(provider_config)
                results[provider_name] = OIDCProviderHealth(
                    status=ServiceStatus.HEALTHY,
                    issuer=provider_config.issuer,
                )
            except Exception as e:
                results[provider_name] = OIDCProviderHealth(
                    status=ServiceStatus.UNHEALTHY,
                    issuer=provider_config.issuer,
                    error=str(e),
                )

        return results if results else None

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _get_database_type(self) -> str:
        """Determine database type from connection URL."""
        if "postgresql" in self._config.database.url:
            return "postgresql"
        elif "sqlite" in self._config.database.url:
            return "sqlite"
        else:
            return "unknown"

    def _evaluate_overall_health(
        self,
        database: DatabaseHealth,
        redis: RedisHealth,
        temporal: TemporalHealth,
        oidc_providers: dict[str, OIDCProviderHealth] | None,
    ) -> bool:
        """Evaluate overall health based on individual service checks.

        Critical services:
        - Database: Always critical
        - Temporal: Critical only if enabled
        - OIDC: Critical only in production

        Non-critical services:
        - Redis: Falls back to in-memory, never critical

        Args:
            database: Database health check result
            redis: Redis health check result
            temporal: Temporal health check result
            oidc_providers: OIDC provider health check results

        Returns:
            True if all critical services are healthy
        """
        # Database is always critical
        if database.status == ServiceStatus.UNHEALTHY:
            return False

        # Temporal is critical only if enabled
        if temporal.status == ServiceStatus.UNHEALTHY:
            return False

        # OIDC is critical only in production
        if oidc_providers and self._config.app.environment == "production":
            for provider in oidc_providers.values():
                if provider.status == ServiceStatus.UNHEALTHY:
                    return False

        # Redis is never critical (falls back to in-memory)
        # So we don't check redis.status here

        return True
