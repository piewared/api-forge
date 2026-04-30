"""Application lifespan: dependency wiring, startup health checks, shutdown."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from src.app.api.http.app_data import ApplicationDependencies, DbSessionService
from src.app.api.http.deps import _CSRF_BYPASS_ENVIRONMENTS
from src.app.api.http.health_checks import run_startup_health_checks
from src.app.api.http.middleware.limiter import (
    close_rate_limiter,
    initialize_rate_limiter,
)
from src.app.api.utils.app_startup import configure_logging
from src.app.core.services import (
    AuthSessionService,
    JWKSCacheInMemory,
    JwksService,
    JwtGeneratorService,
    JwtVerificationService,
    OidcClientService,
    RedisService,
    TemporalClientService,
    UserSessionService,
)
from src.app.core.services.storage.factory import get_session_storage, get_storage
from src.app.runtime.context import get_config


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    await startup(app)
    try:
        yield
    finally:
        await shutdown(app)


async def startup(app: FastAPI) -> None:
    """Initialise dependencies, run health checks, prepare the rate limiter.

    Raises ``RuntimeError`` in production if any critical health check or JWKS
    readiness probe fails — outside production these are logged and tolerated.
    """
    configure_logging()

    config = get_config()

    logger.info("Initializing database schema")
    try:
        from src.app.runtime.init_db import init_db

        init_db()
        logger.info("Database schema initialized successfully")
    except Exception:
        logger.exception("Failed to initialize database schema")
        raise

    logger.info("Starting application dependencies initialization")
    try:
        jwks_cache = JWKSCacheInMemory(
            max_entries=config.jwt.jwks_cache_max_entries,
            ttl_seconds=config.jwt.jwks_cache_ttl_seconds,
        )
        jwks_service = JwksService(jwks_cache)
        jwt_verify_service = JwtVerificationService(jwks_service)
        jwt_generation_service = JwtGeneratorService()

        redis_service: RedisService | None = None
        if config.redis.enabled:
            logger.info("Creating Redis service")
            redis_service = RedisService()
            if await redis_service.health_check():
                logger.info("Redis service is available")
            else:
                logger.warning("Redis service is not available")
                redis_service = None

        logger.info("Setting up storage services")
        app_storage = get_storage(redis_service)
        session_storage = get_session_storage(redis_service)

        logger.info("Creating user session services")
        user_session_service = UserSessionService(session_storage)

        logger.info("Creating authentication session service")
        auth_session_service = AuthSessionService(session_storage)

        logger.info("Creating database session service")
        database_service = DbSessionService()

        logger.info("Creating OIDC client service")
        oidc_client_service = OidcClientService(jwt_verify_service)

        logger.info("Creating Temporal client service")
        temporal_service = TemporalClientService()

        logger.info("Finalizing application dependencies")
        deps = ApplicationDependencies(
            jwks_cache=jwks_cache,
            jwks_service=jwks_service,
            jwt_verify_service=jwt_verify_service,
            jwt_generation_service=jwt_generation_service,
            app_storage=app_storage,
            oidc_client_service=oidc_client_service,
            user_session_service=user_session_service,
            auth_session_service=auth_session_service,
            database_service=database_service,
            redis_service=redis_service,
            temporal_service=temporal_service,
        )
    except Exception:
        logger.exception("Failed to initialize application dependencies")
        raise

    app.state.app_dependencies = deps

    logger.info("Starting up application in {} environment", config.app.environment)

    # CSRF / Origin enforcement is bypassed in dev and test environments. If
    # this is misconfigured in production (env not set / set to "development"),
    # the bypass would silently disable a critical defense — log it loudly.
    if config.app.environment in _CSRF_BYPASS_ENVIRONMENTS:
        logger.warning(
            "CSRF + Origin enforcement is BYPASSED for env='{}'. "
            "Make sure APP_ENVIRONMENT is set to 'production' before deploying.",
            config.app.environment,
        )

    logger.info("Performing startup health checks on critical services")
    health_check_errors = await run_startup_health_checks(deps, config)

    if not config.redis.enabled:
        logger.info("Redis is disabled in config, skipping health check")
    elif deps.redis_service is None:
        logger.info(
            "Redis unavailable (connection failed during startup), skipping periodic health check"
        )

    if not config.temporal.enabled:
        logger.info("Temporal is disabled, skipping health check")

    if health_check_errors and config.app.environment == "production":
        error_summary = "; ".join([f"{svc}: {err}" for svc, err in health_check_errors])
        raise RuntimeError(f"Critical service health checks failed: {error_summary}")
    elif health_check_errors:
        logger.warning(
            "Some health checks failed but continuing: {}", health_check_errors
        )

    # Verify JWKS endpoints so auth failures surface early.
    if config.oidc.providers:
        jwks_svc: JwksService = app.state.app_dependencies.jwks_service
        issuers = list(config.oidc.providers.values())
        results = await asyncio.gather(
            *(jwks_svc.fetch_jwks(iss) for iss in issuers), return_exceptions=True
        )
        errors = [
            (iss, str(err))
            for iss, err in zip(issuers, results, strict=True)
            if isinstance(err, Exception)
        ]
        for iss, err in errors:
            logger.exception("Failed to fetch JWKS for issuer {}: {}", iss, err)
        if errors and config.app.environment == "production":
            raise RuntimeError(f"JWKS readiness check failed for issuers: {errors}")

    await initialize_rate_limiter(app)


async def shutdown(app: FastAPI) -> None:
    logger.info("Shutting down application")
    await close_rate_limiter()
    app_dependencies: ApplicationDependencies = app.state.app_dependencies
    await app_dependencies.auth_session_service.purge_expired()
    await app_dependencies.user_session_service.purge_expired()
    if app_dependencies.redis_service is not None:
        await app_dependencies.redis_service.close()
    await app_dependencies.temporal_service.close()
