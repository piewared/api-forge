from typing import Any, override

from src.app.core.services.storage.base import ApplicationStorage, T


class SessionStorage(ApplicationStorage):
    def __init__(self, storage: ApplicationStorage) -> None:
        self._storage = storage

    async def list_sessions(self, pattern: str, model_class: type[T]) -> list[T]:
        """List sessions matching a pattern.

        Args:
            pattern: Key pattern (e.g., "auth:*", "user:*")
            model_class: Pydantic model class to deserialize to

        Returns:
            List of valid, non-expired sessions
        """
        try:
            sessions = []
            keys = await self._storage.list_keys(pattern)

            for key in keys:
                try:
                    session = await self._storage.get(key, model_class)
                    if session:
                        sessions.append(session)
                except Exception:
                    # Skip corrupted/invalid sessions
                    continue

            return sessions
        except Exception as e:
            self._available = False
            raise RuntimeError(f"Redis list sessions failed: {e}") from e

    @override
    async def set(self, key: str, value: T, ttl_seconds: int) -> None:
        """Store a session."""
        await self._storage.set(key, value, ttl_seconds)

    @override
    async def get(self, key: str, model_class: type[T] | None) -> T | Any | None:
        """Retrieve a session."""
        return await self._storage.get(key, model_class)

    @override
    async def delete(self, key: str) -> None:
        """Delete a session."""
        await self._storage.delete(key)

    @override
    async def exists(self, key: str) -> bool:
        """Check if a session exists."""
        return await self._storage.exists(key)

    @override
    async def cleanup_expired(self) -> int:
        """Clean up expired sessions."""
        return await self._storage.cleanup_expired()

    @override
    async def list_keys(self, pattern: str) -> list[str]:
        """List keys matching a pattern."""
        return await self._storage.list_keys(pattern)

    @override
    def is_available(self) -> bool:
        """Check if storage backend is available."""
        return self._storage.is_available()
