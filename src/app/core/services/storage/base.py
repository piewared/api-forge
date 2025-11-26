"""Session storage interface and implementations.

Provides a unified interface for storing auth sessions and user sessions
wi        self._data[key] = {
            "data": json.loads(value.model_dump_json()),
            "expires_at": expires_at,
        }

    @override
    async def get(self, key: str, model_class: type[T] | None) -> T | Any | None:is-first approach and in-memory fallback.
"""

from abc import ABC, abstractmethod
from typing import Any, TypeVar, overload

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ApplicationStorage(ABC):
    """Abstract interface for session storage backends."""

    @abstractmethod
    async def set(self, key: str, value: BaseModel, ttl_seconds: int) -> None:
        """Store a session with TTL.

        Args:
            key: Session identifier
            value: Session data (Pydantic model)
            ttl_seconds: Time to live in seconds
        """
        pass

    @overload
    async def get(self, key: str, model_class: None) -> Any | None: ...

    @overload
    async def get(self, key: str, model_class: type[T]) -> T | None: ...

    @abstractmethod
    async def get(self, key: str, model_class: type[T] | None) -> T | Any | None:
        """Retrieve a session.

        Args:
            key: Session identifier
            model_class: Pydantic model class to deserialize to

        Returns:
            Session data or None if not found/expired
        """
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a session.

        Args:
            key: Session identifier
        """
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if session exists.

        Args:
            key: Session identifier

        Returns:
            True if session exists and not expired
        """
        pass

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Clean up expired sessions.

        Returns:
            Number of sessions cleaned up
        """
        pass

    @abstractmethod
    async def list_keys(self, pattern: str) -> list[str]:
        """List keys matching a pattern.

        Args:
            pattern: Key pattern (e.g., "auth:*", "user:*")

        Returns:
            List of matching keys
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if storage backend is available.

        Returns:
            True if storage is healthy and available
        """
        pass
