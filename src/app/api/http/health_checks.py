"""Concurrent startup health checks for critical services."""

from __future__ import annotations

import asyncio

from loguru import logger

from src.app.api.http.app_data import ApplicationDependencies
from src.app.core.services import DbSessionService
from src.app.runtime.context import ConfigData


async def _check_database(service: DbSessionService) -> bool:
    return await asyncio.to_thread(service.health_check)


async def run_startup_health_checks(
    deps: ApplicationDependencies, config: ConfigData
) -> list[tuple[str, str]]:
    """Run all startup health checks concurrently.

    Returns a list of ``(service_name, error)`` tuples for failed checks. An
    empty list means everything is healthy. Caller decides whether to abort
    startup or continue.
    """
    tasks: dict[str, asyncio.Task[bool]] = {}
    tasks["database"] = asyncio.create_task(_check_database(deps.database_service))
    if deps.redis_service is not None:
        tasks["redis"] = asyncio.create_task(deps.redis_service.health_check())
    if config.temporal.enabled:
        tasks["temporal"] = asyncio.create_task(deps.temporal_service.health_check())

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    errors: list[tuple[str, str]] = []
    for name, result in zip(tasks.keys(), results, strict=True):
        if isinstance(result, Exception):
            logger.exception("{} health check failed: {}", name, result)
            errors.append((name, str(result)))
        elif not result:
            msg = f"{name} health check returned unhealthy status"
            logger.error(msg)
            errors.append((name, msg))
        else:
            logger.info("✓ {} is healthy", name)
    return errors
