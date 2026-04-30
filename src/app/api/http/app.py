"""FastAPI application factory.

This module is intentionally thin: it wires the FastAPI instance to its
middleware, lifespan, and routers and exposes ``app`` for ASGI servers.
Implementation details live in single-purpose modules:

- ``lifespan`` — startup/shutdown sequencing and dependency wiring
- ``health_checks`` — concurrent readiness probes
- ``middleware/security_headers`` — security headers
- ``middleware/cors`` — CORS configuration
- ``middleware/request_logging`` — correlation IDs and request log lines
- ``middleware/limiter`` — rate-limiter init/shutdown
"""

from __future__ import annotations

from fastapi import FastAPI

from src.app.api.http.lifespan import lifespan
from src.app.api.http.middleware.cors import configure_cors
from src.app.api.http.middleware.limiter import (
    configure_rate_limiter,  # re-exported for tests
)
from src.app.api.http.middleware.request_logging import log_requests
from src.app.api.http.middleware.security_headers import SecurityHeadersMiddleware
from src.app.api.http.routers.auth import router_jit
from src.app.api.http.routers.auth_bff_enhanced import router_bff
from src.app.api.http.routers.health import router as health_router
from src.app.api.http.routers.loader import register_entity_routers
from src.app.runtime.context import get_config

__all__ = ["app", "create_app", "configure_rate_limiter"]


def _register_core_routers(app: FastAPI) -> None:
    """Register framework-level routers that aren't entity-scoped."""
    app.include_router(health_router)
    app.include_router(router_jit, prefix="/auth")
    app.include_router(router_bff, prefix="/auth")


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(
        lifespan=lifespan,
        docs_url=None if config.app.environment == "production" else "/docs",
        redoc_url=None if config.app.environment == "production" else "/redoc",
    )
    app.add_middleware(SecurityHeadersMiddleware)
    configure_cors(app)
    app.middleware("http")(log_requests)
    _register_core_routers(app)
    register_entity_routers(app)
    return app


app = create_app()
