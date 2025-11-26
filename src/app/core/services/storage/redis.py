from typing import TYPE_CHECKING, Any, override

from pydantic import BaseModel

from src.app.core.services.storage.base import ApplicationStorage, T

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisStorage(ApplicationStorage):
    """Redis-based session storage with serialization."""

    def __init__(self, redis_client: "Redis") -> None:
        self._redis = redis_client
        self._available = True

    @override
    async def set(self, key: str, value: BaseModel, ttl_seconds: int) -> None:
        """Store session in Redis with TTL."""
        try:
            data = value.model_dump_json()
            await self._redis.setex(key, ttl_seconds, data)
            self._available = True
        except Exception as e:
            self._available = False
            raise RuntimeError(f"Redis set failed: {e}") from e

    @override
    async def get(self, key: str, model_class: type[T] | None) -> T | Any | None:
        """Retrieve session from Redis."""
        try:
            data = await self._redis.get(key)
            if data is None:
                return None

            # Decode if bytes
            if isinstance(data, bytes):
                data = data.decode("utf-8")

            if model_class is None:
                return data

            return model_class.model_validate_json(data)
        except Exception as e:
            self._available = False
            raise RuntimeError(f"Redis get failed: {e}") from e

    @override
    async def delete(self, key: str) -> None:
        """Delete session from Redis."""
        try:
            await self._redis.delete(key)
            self._available = True
        except Exception as e:
            self._available = False
            raise RuntimeError(f"Redis delete failed: {e}") from e

    @override
    async def exists(self, key: str) -> bool:
        """Check if session exists in Redis."""
        try:
            result = await self._redis.exists(key)
            self._available = True
            return bool(result)
        except Exception as e:
            self._available = False
            raise RuntimeError(f"Redis exists failed: {e}") from e

    @override
    async def cleanup_expired(self) -> int:
        """Redis handles expiration automatically."""
        return 0

    @override
    async def list_keys(self, pattern: str) -> list[str]:
        """List keys matching a pattern using Redis SCAN."""
        try:
            keys = []
            cursor = 0

            while True:
                cursor, batch = await self._redis.scan(cursor, match=pattern, count=100)
                keys.extend(batch)

                if cursor == 0:
                    break

            self._available = True
            return keys
        except Exception as e:
            self._available = False
            raise RuntimeError(f"Redis scan failed: {e}") from e

    @override
    def is_available(self) -> bool:
        """Check if Redis connection is healthy."""
        return self._available

    async def ping(self) -> bool:
        """Test Redis connection health."""
        try:
            await self._redis.ping()
            self._available = True
            return True
        except Exception:
            self._available = False
            return False
