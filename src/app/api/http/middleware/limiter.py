"""Rate limiting helpers used by the HTTP layer."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

from fastapi import HTTPException, Request, Response
from loguru import logger

from src.app.runtime.context import get_config

try:
    from fastapi_limiter.depends import RateLimiter

    _has_external = True
except Exception:  # pragma: no cover - optional dependency
    RateLimiter = None  # type: ignore
    _has_external = False


RateLimiterType = Callable[
    [Request, Response], Awaitable[Any]
]  # A rate limiter callable

RateLimiterFactory = Callable[
    [int, int, bool, bool], RateLimiterType
]  # A factory that produces a rate limiter callable

_rate_limiter_factory: RateLimiterFactory | None = None
_local_limiters: list[DefaultLocalRateLimiter] = []  # Track local limiter instances
_factory_counter: int = 0  # Track factory changes for cache invalidation


class DefaultLocalRateLimiter:
    """Simple in-memory limiter used when Redis isn't available."""

    def __init__(
        self, times: int, milliseconds: int, per_endpoint: bool, per_method: bool
    ) -> None:
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._times = times
        self._seconds = milliseconds // 1000
        self._per_endpoint = per_endpoint
        self._per_method = per_method
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = 60.0  # seconds

    async def __call__(self, request: Request, response: Response) -> Any:
        key = self._make_key(
            request,
            per_endpoint=self._per_endpoint,
            per_method=self._per_method,
        )

        await self._throttle(key, self._times, self._seconds)

    def _make_key(
        self, request: Request, *, per_endpoint: bool, per_method: bool
    ) -> str:
        uid = getattr(request.state, "uid", None)
        if uid is not None:
            ident = f"user:{uid}"
        else:
            client_host = request.client.host if request.client else "anonymous"
            ident = f"ip:{client_host}"

        path_piece = ""
        if per_endpoint:
            route = request.scope.get("route")
            template = getattr(route, "path", None)
            path_piece = (template or request.url.path).rstrip("/")

        method_piece = request.method if per_method else ""

        parts = [ident]
        if method_piece:
            parts.append(method_piece)
        if path_piece:
            parts.append(path_piece)
        return ":".join(parts)

    async def _cleanup_old_keys(self) -> None:
        """Remove empty or very old key entries to prevent memory leaks."""
        now = time.monotonic()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = now
        keys_to_remove = []

        for key, hits in self._hits.items():
            # Remove very old entries
            while hits and hits[0] <= now - self._seconds * 2:
                hits.popleft()
            # Mark empty deques for removal
            if not hits:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._hits[key]

    async def cleanup(self) -> None:
        """Clean up resources for this rate limiter instance."""
        async with self._lock:
            self._hits.clear()
            logger.debug(
                f"Cleaned up local rate limiter with {len(self._hits)} tracked keys"
            )

    async def _throttle(self, key: str, times: int, seconds: int) -> None:
        await self._cleanup_old_keys()  # Add periodic cleanup
        now = time.monotonic()
        window_start = now - seconds
        async with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= window_start:
                hits.popleft()
            if len(hits) >= times:
                retry_after = max(0, int(seconds - (now - hits[0])))
                raise HTTPException(
                    status_code=429,
                    detail="Too Many Requests",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)


def configure_rate_limiter(
    limiter_factory: RateLimiterFactory | None = None,
) -> None:
    """Configure which limiter implementation should be used."""

    global _rate_limiter_factory, _local_limiters, _factory_counter

    if not limiter_factory and not _has_external:
        raise RuntimeError("Cannot enable redis rate limiter; dependencies missing")

    # Clear cache when factory changes
    _create_rate_limiter.cache_clear()
    _factory_counter += 1

    if limiter_factory:
        _rate_limiter_factory = limiter_factory
    elif RateLimiter:
        logger.info("Using Redis-backed rate limiter from fastapi-limiter package")

        def redis_rate_limiter_factory(
            times: int, milliseconds: int, per_endpoint: bool, per_method: bool
        ) -> RateLimiterType:
            if not RateLimiter:
                raise RuntimeError("RateLimiter not available")
            # fastapi-limiter expects 'times' and 'seconds', not milliseconds
            return RateLimiter(times=times, milliseconds=milliseconds)

        _rate_limiter_factory = redis_rate_limiter_factory
    else:
        # Use local limiter with tracking
        def local_rate_limiter_factory(
            times: int, milliseconds: int, per_endpoint: bool, per_method: bool
        ) -> RateLimiterType:
            limiter = DefaultLocalRateLimiter(
                times, milliseconds, per_endpoint, per_method
            )
            _local_limiters.append(limiter)  # Track for cleanup
            return limiter

        _rate_limiter_factory = local_rate_limiter_factory
        logger.info("Using local in-memory rate limiter")


@lru_cache(maxsize=100)
def _create_rate_limiter(
    requests: int,
    window_ms: int,
    per_endpoint: bool,
    per_method: bool,
    factory_id: int,  # Use factory ID instead of factory itself
) -> RateLimiterType:
    """Create a rate limiter with specific configuration (cached)."""
    if _rate_limiter_factory is None:
        raise RuntimeError("Rate limiter not configured")
    return _rate_limiter_factory(requests, window_ms, per_endpoint, per_method)


def get_rate_limiter(
    requests: int | None = None,
    window_ms: int | None = None,
) -> RateLimiterType:
    """Get a rate limiter instance for the given configuration."""
    config = get_config()
    final_requests = requests if requests is not None else config.rate_limiter.requests
    final_window_ms = (
        window_ms if window_ms is not None else config.rate_limiter.window_ms
    )

    # Use cached instance based on complete configuration including factory version
    return _create_rate_limiter(
        final_requests,
        final_window_ms,
        config.rate_limiter.per_endpoint,
        config.rate_limiter.per_method,
        _factory_counter,  # Include factory version in cache key
    )


def rate_limit(
    requests: int | None = None,
    window_ms: int | None = None,
) -> RateLimiterType:
    """Return a dependency enforcing request quotas.

    Args:
        requests: Number of requests allowed (defaults to config value)
        window_ms: Time window in milliseconds (defaults to config value)
    """

    async def dependency(request: Request, response: Response) -> Any:
        limiter = get_rate_limiter(requests, window_ms)
        return await limiter(request, response)

    return dependency


async def close_rate_limiter() -> None:
    """Clean up rate limiter resources and clear caches."""
    global _rate_limiter_factory, _local_limiters

    try:
        # Clear the LRU cache to remove all cached limiter instances
        _create_rate_limiter.cache_clear()
        logger.info("Cleared rate limiter cache")

        # Clean up local rate limiter instances
        if _local_limiters:
            logger.info(
                f"Cleaning up {len(_local_limiters)} local rate limiter instances"
            )
            for limiter in _local_limiters:
                if hasattr(limiter, "cleanup"):
                    await limiter.cleanup()
            _local_limiters.clear()

        # For fastapi-limiter, we need to close the FastAPILimiter
        if _has_external and RateLimiter:
            try:
                # Import FastAPILimiter for cleanup
                from fastapi_limiter import FastAPILimiter

                if hasattr(FastAPILimiter, "aclose"):
                    # Use the new aclose() method (fastapi-limiter >= 5.0.1)
                    await FastAPILimiter.aclose()  # type: ignore[attr-defined]
                    logger.info("Closed FastAPILimiter Redis connections")
                elif hasattr(FastAPILimiter, "close"):
                    # Fallback to deprecated close() method
                    await FastAPILimiter.close()
                    logger.info("Closed FastAPILimiter Redis connections")
            except ImportError:
                # FastAPILimiter not available, skip cleanup
                pass
            except Exception as e:
                logger.warning(f"Error closing FastAPILimiter: {e}")

        # Reset the factory
        _rate_limiter_factory = None

        logger.info("Rate limiter cleanup completed")

    except Exception as e:
        logger.error(f"Error during rate limiter cleanup: {e}")
        raise
