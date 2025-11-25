"""Redis connection service for managing Redis client lifecycle and health checks."""

from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from src.app.runtime.context import get_config

if TYPE_CHECKING:
    from redis.asyncio import Redis

class RedisService:
    """Service for managing Redis connection lifecycle and health checks.

    This service provides a centralized Redis client for the application,
    managing connection pooling, health checks, and graceful shutdown.
    Follows the same pattern as DbSessionService for consistency.
    """

    def __init__(self):
        """Initialize the Redis service with connection pooling."""
        logger.info("Setting up Redis service")
        config = get_config()
        redis_config = config.redis

        self._enabled = redis_config.enabled
        self._client = None
        self._url = redis_config.url
        self._connection_string = redis_config.connection_string

        if not self._enabled:
            logger.info("Redis is disabled, service will not connect")
            return

        if not self._url:
            logger.warning("Redis URL not configured, service will not connect")
            self._enabled = False
            self._client = None
            return

        try:
            # Import Redis dependencies (optional dependencies)
            import redis.asyncio as redis_async

            # Try to import Redis dependencies, but handle gracefully if not installed
            from redis.backoff import ExponentialBackoff
            from redis.client import Retry

            logger.info(
                "Initializing Redis client with connection string: {}",
                redis_config.sanitized_connection_string,
            )

            retry = Retry(
                ExponentialBackoff(base=1, cap=10),  # 1s, 2s, 4s, … up to 10s
                retries=6,                           # try up to 6 times
            )

            # Create Redis client with connection pooling
            self._client = redis_async.from_url(
                self._connection_string,          # e.g. rediss://user:pass@host:6379/0
                encoding="utf-8",
                decode_responses=redis_config.decode_responses,
                encoding_errors="replace",
                max_connections=redis_config.max_connections,
                socket_timeout=redis_config.socket_timeout,
                socket_connect_timeout=redis_config.socket_connect_timeout,
                socket_keepalive=True,
                socket_keepalive_options={},
                health_check_interval=30,
                retry=retry,
                client_name="my_app_redis_client",
                # ssl=True, ssl_cert_reqs="required",  # ← if TLS isn’t in URL
)

            logger.info(
                "Redis client initialized",
                extra={
                    "url": self._url,
                    "max_connections": redis_config.max_connections,
                    "socket_timeout": redis_config.socket_timeout,
                },
            )
        except ImportError:
            logger.warning("Redis dependencies not installed, service will not connect")
            self._enabled = False
            self._client = None
        except Exception as e:
            logger.error(
                "Failed to initialize Redis client",
                extra={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            self._enabled = False
            self._client = None
            if config.app.environment == "production":
                raise

    def get_client(self) -> Optional['Redis']:
        """Get the Redis async client instance.

        Returns:
            Redis async client if enabled and connected, None otherwise.
        """
        if not self._enabled:
            logger.debug("Redis is disabled, returning None")
            return None

        if not self._client:
            logger.warning("Redis client not initialized, returning None")
            return None

        return self._client

    async def health_check(self) -> bool:
        """Perform a health check on the Redis connection.

        Returns:
            True if Redis is healthy and reachable, False otherwise.
        """
        if not self._enabled:
            logger.debug("Redis is disabled, health check skipped")
            return False

        if not self._client:
            logger.warning("Redis client not initialized, health check failed")
            return False

        try:
            # Use PING command to verify connection
            await self._client.ping()
            return True
        except Exception as e:
            logger.error(
                "Redis health check failed",
                extra={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            return False

    async def get_info(self) -> dict[str, Any] | None:
        """Get Redis server information for monitoring.

        Returns:
            Dictionary with Redis server info, or None if not available.
        """
        if not self._enabled or not self._client:
            return None

        try:
            info = await self._client.info()
            return {
                "version": info.get("redis_version"),
                "uptime_seconds": info.get("uptime_in_seconds"),
                "connected_clients": info.get("connected_clients"),
                "used_memory_human": info.get("used_memory_human"),
                "total_commands_processed": info.get("total_commands_processed"),
            }
        except Exception as e:
            logger.error(
                "Failed to get Redis info",
                extra={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            return None

    async def test_operation(self) -> bool:
        """Test Redis with an actual set/get/delete operation.

        This performs a more thorough health check than just PING,
        verifying that Redis can actually store and retrieve data.

        Returns:
            True if test operation succeeded, False otherwise.
        """
        if not self._enabled or not self._client:
            return False

        try:
            import time

            test_key = f"health_check_test_{time.time()}"
            test_value = "test"

            # Set with 5 second TTL
            await self._client.setex(test_key, 5, test_value)

            # Get it back
            result = await self._client.get(test_key)

            # Clean up
            await self._client.delete(test_key)

            return result == test_value
        except Exception as e:
            logger.error(
                "Redis test operation failed",
                extra={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            return False

    async def close(self) -> None:
        """Close the Redis connection and clean up resources."""
        if self._client:
            try:
                logger.info("Closing Redis connection")
                await self._client.aclose()
                logger.info("Redis connection closed successfully")
            except Exception as e:
                logger.error(
                    "Error closing Redis connection",
                    extra={
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )
            finally:
                self._client = None

    @property
    def is_enabled(self) -> bool:
        """Check if Redis service is enabled."""
        return self._enabled

    @property
    def url(self) -> str | None:
        """Get the Redis connection URL."""
        return self._url
