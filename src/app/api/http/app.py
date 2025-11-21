"""FastAPI application factory and setup."""

import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from src.app.api.http.app_data import ApplicationDependencies, DbSessionService
from src.app.api.http.middleware.limiter import (
    close_rate_limiter,
    configure_rate_limiter,
)
from src.app.api.http.routers.auth import router_jit
from src.app.api.http.routers.auth_bff_enhanced import router_bff
from src.app.api.http.routers.health import router as health_router
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
from src.app.core.storage.session_storage import get_session_storage
from src.app.runtime.context import get_config

# Load configuration
main_config = get_config()


# Initialize logging
configure_logging()


# --- Rate limiter dependencies ---
try:
    import redis.asyncio as redis_async
    from fastapi_limiter import FastAPILimiter
    from redis.asyncio import Redis as AsyncRedis
except ImportError:  # pragma: no cover - optional dependency missing
    FastAPILimiter = None
    redis_async = None
    AsyncRedis = None


# --- Security middleware ---
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=()"
        )
        # HSTS only in prod
        if get_config().app.environment == "production":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains; preload",
            )
        return response


# --- FastAPI app setup ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Allow FastAPI to run startup/shutdown routines once per process

    await startup()
    try:
        yield
    finally:
        await shutdown()


app = FastAPI(
    lifespan=lifespan,
    docs_url=None if get_config().app.environment == "production" else "/docs",
    redoc_url=None if get_config().app.environment == "production" else "/redoc",
)

app.add_middleware(SecurityHeadersMiddleware)

# expose startup for tests
__all__ = ["app", "startup", "shutdown"]

# --- CORS configuration ---
if get_config().app.environment == "production" and (
    "*" in get_config().app.cors.origins
):
    raise RuntimeError(
        "CORS misconfigured: cannot use '*' with allow_credentials=True in production"
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_config().app.cors.origins,
    allow_credentials=get_config().app.cors.allow_credentials,
    allow_methods=get_config().app.cors.allow_methods,
    allow_headers=get_config().app.cors.allow_headers,
)


# --- Request logging middleware ---
@app.middleware("http")
@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Correlation / tracing
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    # Prefer proxy headers if you run behind a reverse proxy (set up trust chain!)
    xff = request.headers.get("x-forwarded-for")
    client_ip = (
        xff.split(",")[0].strip()
        if xff
        else request.client.host
        if request.client
        else "unknown"
    )

    # query strings may contain secrets; omit or sanitize if needed
    # query = request.url.query or ""

    base_ctx = {
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        # "query": query,
        "client_ip": client_ip,
        "user_agent": request.headers.get("user-agent", "unknown"),
        "http_version": request.scope.get("http_version", "1.1"),
        "scheme": request.url.scheme,
        "host": request.headers.get("host", request.url.hostname or "-"),
        # route name can be handy for metrics/aggregation
        "route_name": getattr(request.scope.get("route"), "name", None),
    }

    start = time.perf_counter()
    response = None

    # Everything that logs within this block inherits base_ctx
    with logger.contextualize(**base_ctx):
        try:
            logger.info("request.start")
            response = await call_next(request)

            duration_ms = (time.perf_counter() - start) * 1000
            logger.bind(
                status_code=response.status_code,
                duration_ms=round(duration_ms, 1),
            ).info("request.end")

            # Attach correlation id
            response.headers.setdefault("X-Request-ID", request_id)
            return response

        except HTTPException as exc:
            # Let FastAPI semantics through, but log once with context.
            duration_ms = (time.perf_counter() - start) * 1000
            logger.bind(
                status_code=exc.status_code,
                duration_ms=round(duration_ms, 1),
                error_type=type(exc).__name__,
            ).exception("request.error")
            # Avoid duplicate logs from ServerErrorMiddleware by returning here.
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail, "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )

        except RequestValidationError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.bind(
                status_code=422,
                duration_ms=round(duration_ms, 1),
                error_type=type(exc).__name__,
            ).exception("request.validation_error")
            return JSONResponse(
                status_code=422,
                content={"detail": exc.errors(), "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )

        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.bind(
                status_code=500,
                duration_ms=round(duration_ms, 1),
                error_type=type(exc).__name__,
            ).exception("request.error")
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error", "request_id": request_id},
                headers={"X-Request-ID": request_id},
            )


# --- Router registration ---
# Health check endpoints
app.include_router(health_router)

# OIDC compliant authentication endpoints
app.include_router(router_jit, prefix="/auth")

# BFF authentication endpoints for web clients
app.include_router(router_bff, prefix="/auth")

# Add your application-specific routers here
# Example:
# app.include_router(your_router, prefix="/api/v1", tags=["your_feature"])


def _activate_local_rate_limiter() -> None:
    from src.app.api.http.middleware.limiter import DefaultLocalRateLimiter

    logger.warning("Falling back to in-memory rate limiter")
    configure_rate_limiter(limiter_factory=DefaultLocalRateLimiter)


# --- Rate limiter setup ---
async def _initialize_rate_limiter() -> None:
    # Skip initialization when Redis is not configured
    config = get_config()
    if config.redis.url is None:
        logger.info("Redis URL not configured; skipping rate limiter initialization")
        _activate_local_rate_limiter()
        return None
    if FastAPILimiter is None or redis_async is None:
        logger.error("Rate limiter deps missing but REDIS_URL provided")
        if config.app.environment == "production":
            raise RuntimeError("Rate limiter dependencies missing in production")
        _activate_local_rate_limiter()
        return

    try:
        logger.info("Initializing FastAPI limiter with Redis: {}", config.redis.url)
        client = redis_async.from_url(
            config.redis.connection_string,
            encoding="utf-8",
            decode_responses=config.redis.decode_responses,
        )
        await FastAPILimiter.init(client)
        app.state.redis = client

        logger.info(
            "FastAPI limiter initialized with Redis: {}", config.redis.sanitized_connection_string
        )
        configure_rate_limiter()  # use default redis-based limiter
        app.state.local_rate_limiter = None
        return
    except Exception:
        logger.exception("Failed to initialize FastAPI limiter with Redis")
        if config.app.environment == "production":
            raise
        _activate_local_rate_limiter()
        return


# --- Lifecycle hooks ---
async def startup() -> None:
    # Initialize application-wide dependencies here
    # e.g. database connections, caches, etc.

    config = get_config()

    logger.info("Initializing database schema")
    try:
        from src.app.runtime.init_db import init_db
        init_db()
        logger.info("Database schema initialized successfully")
    except Exception as e:
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

        logger.info("Setting up session storage and services")
        session_storage = await get_session_storage()

        logger.info("Creating OIDC client service")
        oidc_client_service = OidcClientService(jwt_verify_service)

        logger.info("Creating session services")
        user_session_service = UserSessionService(session_storage)

        logger.info("Creating authentication session service")
        auth_session_service = AuthSessionService(session_storage)

        logger.info("Creating database session service")
        database_service = DbSessionService()

        logger.info("Creating Redis service")
        redis_service = RedisService()

        logger.info("Creating Temporal client service")
        temporal_service = TemporalClientService()

        logger.info("Finalizing application dependencies")
        deps = ApplicationDependencies(
            jwks_cache=jwks_cache,
            jwks_service=jwks_service,
            jwt_verify_service=jwt_verify_service,
            jwt_generation_service=jwt_generation_service,
            oidc_client_service=oidc_client_service,
            user_session_service=user_session_service,
            auth_session_service=auth_session_service,
            database_service=database_service,
            redis_service=redis_service,
            temporal_service=temporal_service,
        )
    except Exception as e:
        logger.exception("Failed to initialize application dependencies")
        # Re-raise to avoid continuing startup with incomplete dependencies
        raise

    app.state.app_dependencies = deps

    logger.info("Getting configuration for startup")
    logger.info("Starting up application in {} environment", config.app.environment)
    # Validate configuration so we fail fast on misconfiguration

    # Perform health checks on critical services
    logger.info("Performing startup health checks on critical services")
    health_check_errors = []

    # Database health check
    try:
        logger.info("Checking database connectivity...")
        db_healthy = deps.database_service.health_check()
        if db_healthy:
            logger.info("✓ Database is healthy")
        else:
            error_msg = "Database health check returned unhealthy status"
            logger.error(error_msg)
            health_check_errors.append(("database", error_msg))
    except Exception as e:
        error_msg = f"Database health check failed: {e}"
        logger.exception(error_msg)
        health_check_errors.append(("database", str(e)))

    # Redis health check (non-critical, just warn)
    if config.redis.enabled:
        try:
            logger.info("Checking Redis connectivity...")
            redis_healthy = await deps.redis_service.health_check()
            if redis_healthy:
                logger.info("✓ Redis is healthy")
            else:
                logger.warning("⚠ Redis health check returned unhealthy status, will use in-memory fallback")
        except Exception as e:
            logger.warning("⚠ Redis health check failed: {}, will use in-memory fallback", e)
    else:
        logger.info("Redis is disabled, skipping health check")

    # Temporal health check (critical if enabled)
    if config.temporal.enabled:
        try:
            logger.info("Checking Temporal connectivity...")
            temporal_healthy = await deps.temporal_service.health_check()
            if temporal_healthy:
                logger.info("✓ Temporal is healthy")
            else:
                error_msg = "Temporal health check returned unhealthy status"
                logger.error(error_msg)
                health_check_errors.append(("temporal", error_msg))
        except Exception as e:
            error_msg = f"Temporal health check failed: {e}"
            logger.exception(error_msg)
            health_check_errors.append(("temporal", str(e)))
    else:
        logger.info("Temporal is disabled, skipping health check")

    # Fail startup if critical services are unhealthy
    if health_check_errors and config.app.environment == "production":
        error_summary = "; ".join([f"{svc}: {err}" for svc, err in health_check_errors])
        raise RuntimeError(f"Critical service health checks failed: {error_summary}")
    elif health_check_errors:
        logger.warning("Some health checks failed but continuing in non-production environment: {}", health_check_errors)

    # Verify JWKS endpoints so auth failures surface early
    if config.oidc.providers:
        jwks_service: JwksService = app.state.app_dependencies.jwks_service
        # issuers = list(main_config.oidc_providers.keys())
        issuers = list(config.oidc.providers.values())
        results = await asyncio.gather(
            *(jwks_service.fetch_jwks(iss) for iss in issuers), return_exceptions=True
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

    await _initialize_rate_limiter()


async def shutdown() -> None:
    logger.info("Shutting down application")
    await close_rate_limiter()
    app_dependencies: ApplicationDependencies = app.state.app_dependencies
    # Clean up application-wide dependencies here
    await app_dependencies.auth_session_service.purge_expired()
    await app_dependencies.user_session_service.purge_expired()
    # Close Redis connection
    await app_dependencies.redis_service.close()
    # Close Temporal client connection
    await app_dependencies.temporal_service.close()


# --- Route handlers ---


if __name__ == "__main__":
    import uvicorn

    # Let uvicorn use its default logging, but our InterceptHandler will:
    # - Keep INFO/WARNING logs (startup, shutdown, connection issues)
    # - Drop ERROR logs (duplicate exceptions)
    # - Drop access logs (we handle in middleware)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        access_log=False,  # We handle access logging in middleware
    )
