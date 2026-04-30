"""Request/response logging middleware with correlation IDs."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.exceptions import HTTPException, RequestValidationError
from loguru import logger
from starlette.responses import JSONResponse


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    # Prefer proxy headers if running behind a reverse proxy (set up trust chain!)
    xff = request.headers.get("x-forwarded-for")
    client_ip = (
        xff.split(",")[0].strip()
        if xff
        else request.client.host
        if request.client
        else "unknown"
    )

    base_ctx = {
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "client_ip": client_ip,
        "user_agent": request.headers.get("user-agent", "unknown"),
        "http_version": request.scope.get("http_version", "1.1"),
        "scheme": request.url.scheme,
        "host": request.headers.get("host", request.url.hostname or "-"),
        "route_name": getattr(request.scope.get("route"), "name", None),
    }

    start = time.perf_counter()

    with logger.contextualize(**base_ctx):
        try:
            logger.info("request.start")
            response = await call_next(request)

            duration_ms = (time.perf_counter() - start) * 1000
            logger.bind(
                status_code=response.status_code,
                duration_ms=round(duration_ms, 1),
            ).info("request.end")

            response.headers.setdefault("X-Request-ID", request_id)
            return response

        except HTTPException as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.bind(
                status_code=exc.status_code,
                duration_ms=round(duration_ms, 1),
                error_type=type(exc).__name__,
            ).exception("request.error")
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
