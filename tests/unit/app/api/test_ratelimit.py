import asyncio
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, Request
from fastapi_limiter.depends import RateLimiter

from src.app.api.http.app import FastAPILimiter, configure_rate_limiter
from src.app.api.http.middleware.limiter import (
    DefaultLocalRateLimiter,
    get_rate_limiter,
)
from src.app.core.services.redis_service import is_redis_available
from src.app.runtime.config.config_data import ConfigData
from src.app.runtime.context import get_config, with_context

# Check Redis availability once at module load time
REDIS_AVAILABLE = is_redis_available()

requires_redis = pytest.mark.skipif(
    not REDIS_AVAILABLE, reason="Redis is not running or not accessible"
)

# Mark Redis tests to run in same xdist group to avoid shared state issues
redis_xdist_group = pytest.mark.xdist_group("redis_rate_limiter")


class TestRateLimiting:
    """Test rate limiting functionality."""

    @pytest.fixture
    def test_config(self) -> ConfigData:
        """Fixture to provide a configuration context."""
        test_config = ConfigData()
        # set_config(test_config)
        return test_config

    @pytest.fixture(
        params=[
            "local",
            pytest.param(
                "redis",
                marks=[requires_redis, redis_xdist_group],
            ),
        ]
    )
    async def rate_limiter_type(self, test_config, request):
        """Parametrized fixture that provides both local and redis rate limiters."""
        with with_context(test_config):
            limiter_type = request.param

            if limiter_type == "local":
                # Configure local rate limiter
                def local_factory(
                    times: int, milliseconds: int, per_endpoint: bool, per_method: bool
                ):
                    return DefaultLocalRateLimiter(
                        times, milliseconds, per_endpoint, per_method
                    )

                configure_rate_limiter(local_factory)
                return "local"

            elif limiter_type == "redis":
                # Configure Redis rate limiter - initialization will be done in test setup
                configure_rate_limiter()  # Use default redis configuration
                return "redis"

    @pytest.fixture
    async def get_limiter(self, rate_limiter_type):
        """Factory fixture that creates rate limiters based on the configured type."""

        def _get_limiter(requests: int = 5, window_ms: int = 60000):
            return get_rate_limiter(requests, window_ms)

        return _get_limiter

    @pytest.fixture
    async def redis_setup(self, rate_limiter_type):
        """Setup Redis connection if needed for Redis rate limiter tests."""
        if rate_limiter_type == "redis":
            # Initialize Redis connection for FastAPILimiter using async API
            import redis.asyncio as redis_async

            redis_url = get_config().redis.connection_string
            client = redis_async.from_url(
                redis_url, encoding="utf-8", decode_responses=True
            )
            await FastAPILimiter.init(client)

            # Clear any existing rate limiting data for clean test state
            await client.flushdb()

            yield

            # Cleanup - clear data and close connection
            await client.flushdb()
            # Use aclose() directly instead of FastAPILimiter.close() to avoid deprecation warning
            await client.aclose()
            # Reset FastAPILimiter state
            FastAPILimiter.redis = None
        else:
            yield

    @pytest.mark.asyncio
    async def test_rate_limiter_creation(
        self, rate_limiter_type, get_limiter, redis_setup
    ):
        """Test creating local and external rate limiters."""
        limiter = get_limiter(5, 60000)

        if rate_limiter_type == "local":
            assert isinstance(limiter, DefaultLocalRateLimiter)
            assert limiter._hits is not None
            assert limiter._lock is not None
        elif rate_limiter_type == "redis":
            assert isinstance(limiter, RateLimiter)
            assert limiter.times is not None
            assert limiter.milliseconds is not None

    @pytest.fixture
    def mock_request(self):
        """Create a mock request for testing."""
        request = Mock(spec=Request)
        request.client = Mock()
        request.client.host = "127.0.0.1"
        request.state = Mock()
        request.scope = {"route": None, "path": "/test"}
        request.method = "GET"
        request.url = Mock()
        request.url.path = "/test"

        # Add mock app with routes for fastapi-limiter compatibility
        request.app = Mock()
        request.app.routes = []  # Empty routes list for testing

        # Add mock headers for fastapi-limiter identifier
        request.headers = Mock()
        request.headers.get = Mock(return_value=None)  # No forwarded headers by default

        return request

    @pytest.mark.asyncio
    async def test_rate_limiting_within_limits(
        self, get_limiter, mock_request, redis_setup
    ):
        """Test rate limiting allows requests within limits."""
        limiter = get_limiter(5, 60000)
        response = Mock()

        # Should allow first few requests
        for _ in range(5):
            await limiter(mock_request, response)

    @pytest.mark.asyncio
    async def test_rate_limiting_exceeds_limits(
        self, get_limiter, mock_request, redis_setup
    ):
        """Test rate limiting blocks requests exceeding limits."""
        limiter = get_limiter(1, 60000)  # Very low limit
        response = Mock()

        # First request should pass
        await limiter(mock_request, response)

        # Second request should be blocked
        with pytest.raises(HTTPException) as exc_info:
            await limiter(mock_request, response)

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_rate_limiting_time_window_reset(
        self, get_limiter, mock_request, redis_setup
    ):
        """Test rate limits reset after time window expires."""
        limiter = get_limiter(1, 1000)  # 1 request per 1 second
        response = Mock()

        # First request should pass
        await limiter(mock_request, response)

        # Second request should be blocked
        with pytest.raises(HTTPException):
            await limiter(mock_request, response)

        # Wait for window to expire
        await asyncio.sleep(1.1)

        # Should allow request again after window reset
        await limiter(mock_request, response)

    @pytest.mark.asyncio
    async def test_rate_limiting_different_clients(self, get_limiter, redis_setup):
        """Test rate limiting per client IP address."""
        limiter = get_limiter(1, 60000)
        response = Mock()

        # Create requests from different IPs
        request1 = Mock(spec=Request)
        request1.client = Mock()
        request1.client.host = "192.168.1.1"
        request1.state = Mock()
        request1.scope = {"route": None, "path": "/test"}
        request1.method = "GET"
        request1.url = Mock()
        request1.url.path = "/test"
        request1.app = Mock()
        request1.app.routes = []
        request1.headers = Mock()
        request1.headers.get = Mock(return_value=None)

        request2 = Mock(spec=Request)
        request2.client = Mock()
        request2.client.host = "192.168.1.2"
        request2.state = Mock()
        request2.scope = {"route": None, "path": "/test"}
        request2.method = "GET"
        request2.url = Mock()
        request2.url.path = "/test"
        request2.app = Mock()
        request2.app.routes = []
        request2.headers = Mock()
        request2.headers.get = Mock(return_value=None)

        # Each client should be able to make one request
        await limiter(request1, response)
        await limiter(request2, response)

        # Both should be blocked for second requests
        with pytest.raises(HTTPException):
            await limiter(request1, response)

        with pytest.raises(HTTPException):
            await limiter(request2, response)

    @pytest.mark.asyncio
    async def test_rate_limiting_boundary_conditions(
        self, get_limiter, mock_request, redis_setup
    ):
        """Test rate limiting at exact boundaries."""
        limiter = get_limiter(3, 60000)  # 3 requests per 60 seconds
        response = Mock()

        # Should allow exactly 3 requests
        for _ in range(3):
            await limiter(mock_request, response)

        # 4th request should be blocked
        with pytest.raises(HTTPException) as exc_info:
            await limiter(mock_request, response)

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_rate_limiting_concurrent_requests(
        self, get_limiter, mock_request, redis_setup, rate_limiter_type
    ):
        """Test rate limiting handles concurrent requests correctly."""
        limiter = get_limiter(2, 60000)  # 2 requests per 60 seconds

        if rate_limiter_type == "redis":
            assert isinstance(limiter, RateLimiter)
        elif rate_limiter_type == "local":
            assert isinstance(limiter, DefaultLocalRateLimiter)

        response = Mock()

        # Simulate concurrent requests
        async def make_request():
            return await limiter(mock_request, response)

        tasks = [make_request() for _ in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Should have exactly 2 successful requests and 3 exceptions
        successful = [r for r in results if not isinstance(r, Exception)]
        exceptions = [r for r in results if isinstance(r, HTTPException)]

        assert len(successful) == 2
        assert len(exceptions) == 3
        assert all(exc.status_code == 429 for exc in exceptions)

    @pytest.mark.asyncio
    async def test_rate_limit_persists_until_window_expires(
        self, get_limiter, mock_request, redis_setup
    ):
        """Should continue blocking requests until the full window expires."""
        limiter = get_limiter(2, 5000)  # 2 requests per 5 seconds

        response = Mock()

        # Exceed the limit
        for _ in range(2):
            await limiter(mock_request, response)

        with pytest.raises(HTTPException):
            await limiter(mock_request, response)

        # Wait for partial window reset (should still be blocked)
        await asyncio.sleep(4)
        with pytest.raises(HTTPException):
            await limiter(mock_request, response)

        # Wait for full window reset
        await asyncio.sleep(1)
        for _ in range(2):
            await limiter(mock_request, response)

        # Should be blocked again after limit
        with pytest.raises(HTTPException):
            await limiter(mock_request, response)
