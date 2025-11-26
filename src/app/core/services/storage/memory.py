"""Session storage interface and implementations.

Provides a unified interface for storing auth sessions and user sessions
wi        self._data[key] = {
            "data": json.loads(value.model_dump_json()),
            "expires_at": expires_at,
        }

    @override
    async def get(self, key: str, model_class: type[T] | None) -> T | Any | None:is-first approach and in-memory fallback.
"""

from __future__ import annotations

import json
import time
from typing import Any, override

from pydantic import BaseModel

from src.app.core.services.storage.base import ApplicationStorage, T


class InMemoryStorage(ApplicationStorage):
    """In-memory storage with TTL support."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    @override
    async def set(self, key: str, value: BaseModel, ttl_seconds: int) -> None:
        """Store session in memory with expiration."""
        expires_at = time.time() + ttl_seconds
        self._data[key] = {
            "data": json.loads(value.model_dump_json()),
            "expires_at": expires_at,
        }

    async def get(self, key: str, model_class: type[T] | None) -> T | Any | None:
        """Retrieve session from memory if not expired."""
        if key not in self._data:
            return None

        entry = self._data[key]
        if time.time() > entry["expires_at"]:
            del self._data[key]
            return None

        if model_class is None:
            return entry["data"]
        try:
            return model_class.model_validate(entry["data"])
        except Exception:
            # Clean up corrupted data
            del self._data[key]
            return None

    @override
    async def delete(self, key: str) -> None:
        """Delete session from memory."""
        self._data.pop(key, None)

    @override
    async def exists(self, key: str) -> bool:
        """Check if session exists and is not expired."""
        if key not in self._data:
            return False

        entry = self._data[key]
        if time.time() > entry["expires_at"]:
            del self._data[key]
            return False

        return True

    @override
    async def cleanup_expired(self) -> int:
        """Remove expired sessions from memory."""
        now = time.time()
        expired_keys = [
            key for key, entry in self._data.items() if now > entry["expires_at"]
        ]

        for key in expired_keys:
            del self._data[key]

        return len(expired_keys)

    @override
    async def list_keys(self, pattern: str) -> list[str]:
        """List keys matching a pattern using fnmatch."""
        import fnmatch

        matching_keys = []

        for key in self._data.keys():
            if fnmatch.fnmatch(key, pattern):
                # Check if session is still valid (not expired)
                entry = self._data[key]
                if time.time() <= entry["expires_at"]:
                    matching_keys.append(key)
                else:
                    # Clean up expired session
                    del self._data[key]

        return matching_keys

    @override
    def is_available(self) -> bool:
        """In-memory storage is always available."""
        return True
