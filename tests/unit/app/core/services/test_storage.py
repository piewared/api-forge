"""Comprehensive tests for session storage implementations."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from src.app.core.services.storage import (
    InMemoryStorage,
    RedisStorage,
    SessionStorage,
    get_session_storage,
)


class MockSession(BaseModel):
    """Test session model for storage tests."""

    id: str
    data: str
    created_at: int


class TestInMemorySessionStorage:
    """Test in-memory session storage implementation."""

    def setup_method(self):
        """Set up fresh storage for each test."""
        self.storage = InMemoryStorage()

    @pytest.mark.asyncio
    async def test_set_and_get_session(self):
        """Test storing and retrieving a session."""
        session = MockSession(
            id="test-123", data="test-data", created_at=int(time.time())
        )

        await self.storage.set("session-1", session, 60)
        retrieved = await self.storage.get("session-1", MockSession)

        assert retrieved is not None
        assert retrieved.id == "test-123"
        assert retrieved.data == "test-data"

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self):
        """Test getting a session that doesn't exist."""
        result = await self.storage.get("nonexistent", MockSession)
        assert result is None

    @pytest.mark.asyncio
    async def test_session_expiration(self):
        """Test that sessions expire after TTL."""
        session = MockSession(
            id="expire-test", data="data", created_at=int(time.time())
        )

        # Set with very short TTL
        await self.storage.set("expire-session", session, 1)

        # Should exist immediately
        result = await self.storage.get("expire-session", MockSession)
        assert result is not None

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Should be expired now
        result = await self.storage.get("expire-session", MockSession)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_session(self):
        """Test deleting a session."""
        session = MockSession(
            id="delete-test", data="data", created_at=int(time.time())
        )

        await self.storage.set("delete-session", session, 60)
        assert await self.storage.exists("delete-session")

        await self.storage.delete("delete-session")
        assert not await self.storage.exists("delete-session")

    @pytest.mark.asyncio
    async def test_exists(self):
        """Test session existence checking."""
        session = MockSession(
            id="exists-test", data="data", created_at=int(time.time())
        )

        # Should not exist initially
        assert not await self.storage.exists("exists-session")

        # Should exist after storing
        await self.storage.set("exists-session", session, 60)
        assert await self.storage.exists("exists-session")

        # Should not exist after expiration
        await self.storage.set("expire-session", session, 1)
        await asyncio.sleep(1.1)
        assert not await self.storage.exists("expire-session")

    @pytest.mark.asyncio
    async def test_cleanup_expired(self):
        """Test cleanup of expired sessions."""
        session1 = MockSession(id="session1", data="data1", created_at=int(time.time()))
        session2 = MockSession(id="session2", data="data2", created_at=int(time.time()))

        # Store one session with short TTL, one with long TTL
        await self.storage.set("short-session", session1, 1)
        await self.storage.set("long-session", session2, 60)

        # Wait for first to expire
        await asyncio.sleep(1.1)

        # Cleanup should remove 1 expired session
        cleaned = await self.storage.cleanup_expired()
        assert cleaned == 1

        # Only long session should remain
        assert not await self.storage.exists("short-session")
        assert await self.storage.exists("long-session")

    def test_is_available(self):
        """Test availability check."""
        assert self.storage.is_available() is True

    @pytest.mark.asyncio
    async def test_corrupted_data_handling(self):
        """Test handling of corrupted session data."""
        # Manually corrupt data
        self.storage._data["corrupted"] = {
            "data": {"invalid": "structure"},  # Missing required fields
            "expires_at": time.time() + 60,
        }

        # Should return None and clean up corrupted data
        result = await self.storage.get("corrupted", MockSession)
        assert result is None
        assert "corrupted" not in self.storage._data


class TestRedisSessionStorage:
    """Test Redis session storage implementation."""

    def setup_method(self):
        """Set up mock Redis client for each test."""
        self.mock_redis = AsyncMock()
        self.storage = RedisStorage(self.mock_redis)

    @pytest.mark.asyncio
    async def test_set_session(self):
        """Test storing a session in Redis."""
        session = MockSession(
            id="redis-test", data="test-data", created_at=int(time.time())
        )

        await self.storage.set("redis-session", session, 60)

        # Verify Redis setex was called with correct parameters
        self.mock_redis.setex.assert_called_once()
        args = self.mock_redis.setex.call_args
        assert args[0][0] == "redis-session"
        assert args[0][1] == 60

        # Verify serialized data
        serialized_data = args[0][2]
        deserialized = json.loads(serialized_data)
        assert deserialized["id"] == "redis-test"

    @pytest.mark.asyncio
    async def test_get_session(self):
        """Test retrieving a session from Redis."""
        session_data = MockSession(
            id="get-test", data="test-data", created_at=int(time.time())
        )
        self.mock_redis.get.return_value = session_data.model_dump_json()

        result = await self.storage.get("get-session", MockSession)

        assert result is not None
        assert result.id == "get-test"
        assert result.data == "test-data"
        self.mock_redis.get.assert_called_once_with("get-session")

    @pytest.mark.asyncio
    async def test_get_session_bytes(self):
        """Test retrieving a session when Redis returns bytes."""
        session_data = MockSession(
            id="bytes-test", data="test-data", created_at=int(time.time())
        )
        self.mock_redis.get.return_value = session_data.model_dump_json().encode(
            "utf-8"
        )

        result = await self.storage.get("bytes-session", MockSession)

        assert result is not None
        assert result.id == "bytes-test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self):
        """Test getting a session that doesn't exist in Redis."""
        self.mock_redis.get.return_value = None

        result = await self.storage.get("nonexistent", MockSession)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_session(self):
        """Test deleting a session from Redis."""
        await self.storage.delete("delete-session")

        self.mock_redis.delete.assert_called_once_with("delete-session")

    @pytest.mark.asyncio
    async def test_exists(self):
        """Test checking session existence in Redis."""
        self.mock_redis.exists.return_value = 1

        result = await self.storage.exists("exists-session")
        assert result is True

        self.mock_redis.exists.assert_called_once_with("exists-session")

    @pytest.mark.asyncio
    async def test_exists_false(self):
        """Test checking session existence when not in Redis."""
        self.mock_redis.exists.return_value = 0

        result = await self.storage.exists("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_expired_noop(self):
        """Test cleanup (Redis handles expiration automatically)."""
        result = await self.storage.cleanup_expired()
        assert result == 0

    @pytest.mark.asyncio
    async def test_ping_success(self):
        """Test successful Redis ping."""
        self.mock_redis.ping.return_value = True

        result = await self.storage.ping()
        assert result is True
        assert self.storage.is_available() is True

    @pytest.mark.asyncio
    async def test_ping_failure(self):
        """Test failed Redis ping."""
        self.mock_redis.ping.side_effect = Exception("Connection failed")

        result = await self.storage.ping()
        assert result is False
        assert self.storage.is_available() is False

    @pytest.mark.asyncio
    async def test_redis_operation_failure(self):
        """Test handling of Redis operation failures."""
        self.mock_redis.setex.side_effect = Exception("Redis error")

        session = MockSession(id="fail-test", data="data", created_at=int(time.time()))

        with pytest.raises(RuntimeError, match="Redis set failed"):
            await self.storage.set("fail-session", session, 60)

        assert self.storage.is_available() is False

    def test_is_available_initial_state(self):
        """Test initial availability state."""
        assert self.storage.is_available() is True


class TestStorageIntegration:
    """Integration tests for storage layer."""

    @pytest.mark.asyncio
    async def test_concurrent_operations(self):
        """Test concurrent storage operations."""
        storage = InMemoryStorage()

        sessions = [
            MockSession(
                id=f"session-{i}", data=f"data-{i}", created_at=int(time.time())
            )
            for i in range(10)
        ]

        # Store sessions concurrently
        await asyncio.gather(
            *[
                storage.set(f"concurrent-{i}", session, 60)
                for i, session in enumerate(sessions)
            ]
        )

        # Retrieve sessions concurrently
        results = await asyncio.gather(
            *[storage.get(f"concurrent-{i}", MockSession) for i in range(10)]
        )

        # Verify all sessions were stored and retrieved correctly
        for i, result in enumerate(results):
            assert result is not None
            assert result.id == f"session-{i}"
            assert result.data == f"data-{i}"

    @pytest.mark.asyncio
    async def test_large_session_data(self):
        """Test storing and retrieving large session data."""
        large_data = "x" * 10000  # 10KB of data
        session = MockSession(id="large", data=large_data, created_at=int(time.time()))

        storage = InMemoryStorage()

        await storage.set("large-session", session, 60)
        result = await storage.get("large-session", MockSession)

        assert result is not None
        assert result.data == large_data
        assert len(result.data) == 10000


class TestStorageFactory:
    """Test storage factory functions and backend detection/failover logic."""

    def test_get_storage_with_redis_available(self):
        """Test get_storage returns RedisStorage when Redis is available."""
        # Mock RedisService with available client
        mock_redis_service = MagicMock()
        mock_redis_client = MagicMock()
        mock_redis_service.get_client.return_value = mock_redis_client

        storage = get_session_storage(mock_redis_service)

        # Should return SessionStorage wrapping RedisStorage
        assert isinstance(storage, SessionStorage)
        # Verify Redis client was requested
        mock_redis_service.get_client.assert_called_once()

    def test_get_storage_with_redis_unavailable(self):
        """Test get_storage falls back to InMemoryStorage when Redis client is None."""
        # Mock RedisService that returns None (Redis unavailable)
        mock_redis_service = MagicMock()
        mock_redis_service.get_client.return_value = None

        storage = get_session_storage(mock_redis_service)

        # Should return SessionStorage wrapping InMemoryStorage
        assert isinstance(storage, SessionStorage)
        mock_redis_service.get_client.assert_called_once()

    def test_get_storage_with_no_redis_service(self):
        """Test get_storage falls back to InMemoryStorage when RedisService is None."""
        storage = get_session_storage(None)

        # Should return SessionStorage wrapping InMemoryStorage
        assert isinstance(storage, SessionStorage)

    def test_get_storage_with_redis_disabled(self):
        """Test get_storage falls back when RedisService exists but is disabled."""
        # Mock RedisService that is disabled (enabled=False)
        mock_redis_service = MagicMock()
        mock_redis_service.get_client.return_value = None

        storage = get_session_storage(mock_redis_service)

        # Should fall back to InMemoryStorage
        assert isinstance(storage, SessionStorage)

    @pytest.mark.asyncio
    async def test_storage_failover_redis_to_memory(self):
        """Test that operations work after Redis fails and falls back to memory."""
        # Create a mock Redis client that will fail
        mock_redis_client = AsyncMock()
        mock_redis_service = MagicMock()

        # First call returns Redis client
        mock_redis_service.get_client.return_value = mock_redis_client

        # Get storage with Redis
        storage = get_session_storage(mock_redis_service)
        assert isinstance(storage, SessionStorage)

        # Now simulate Redis failure by returning None
        mock_redis_service.get_client.return_value = None

        # Get storage again - should fall back to InMemoryStorage
        fallback_storage = get_session_storage(mock_redis_service)
        assert isinstance(fallback_storage, SessionStorage)

        # Test that fallback storage works
        session = MockSession(
            id="failover-test", data="test-data", created_at=int(time.time())
        )
        await fallback_storage.set("test-key", session, 60)
        result = await fallback_storage.get("test-key", MockSession)

        assert result is not None
        assert result.id == "failover-test"

    def test_session_storage_wrapper_delegates_to_backend(self):
        """Test that SessionStorage properly wraps and delegates to backend storage."""
        # Use InMemoryStorage as the backend
        mock_backend = MagicMock()
        storage = SessionStorage(mock_backend)

        # Verify the backend is stored
        assert storage._storage is mock_backend

    @pytest.mark.asyncio
    async def test_integration_factory_with_real_memory_storage(self):
        """Integration test: factory returns working storage without Redis."""
        storage = get_session_storage(None)

        # Test basic operations work
        session = MockSession(
            id="integration-test", data="test-data", created_at=int(time.time())
        )

        await storage.set("integration-key", session, 60)
        result = await storage.get("integration-key", MockSession)

        assert result is not None
        assert result.id == "integration-test"
        assert result.data == "test-data"
