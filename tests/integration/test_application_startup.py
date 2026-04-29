"""Integration tests for application lifecycle and startup behavior.

Exercises ``src.app.api.http.app.startup()`` end-to-end with two configurations:

- Redis enabled: verifies the rate limiter wires up Redis-backed FastAPILimiter.
- Redis disabled: verifies the local in-memory limiter falls back cleanly and
  ``app.state.app_dependencies`` is populated with InMemoryStorage / no
  RedisService.

Side effects we always neutralise:

- ``init_db`` would touch a real Postgres at module-load time.
- The Redis client construction inside ``_initialize_rate_limiter`` would dial
  out to a real Redis even with our fake limiter installed.
- The startup JWKS readiness check would fetch from the configured providers
  (Microsoft / Google / Keycloak) — patched to a no-op.

The override-via-``with_context`` machinery only respects fields that were
explicitly set during ``ConfigData.__init__``; mutating ``deepcopy(config)``
after the fact doesn't always register in ``model_fields_set``. So we patch
the side-effecting call sites directly rather than wrestling with config
merging.
"""

from __future__ import annotations

import sys
import types

import pytest

from src.app.runtime.context import get_config

config = get_config()

# Run startup tests in the same xdist group: they mutate the shared FastAPI
# app's state, and parallel runs would race on app.state.app_dependencies.
pytestmark = pytest.mark.xdist_group("application_startup")


@pytest.fixture
def neutralized_startup(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Patch the I/O-touching parts of startup to no-ops."""
    # Database schema init.
    monkeypatch.setattr("src.app.runtime.init_db.init_db", lambda: None)

    # JWKS readiness fetch — startup iterates configured providers and tries
    # to reach them; we don't care here.
    async def _noop_fetch_jwks(self, issuer, *, force_refresh=False):  # noqa: ARG001
        return {"keys": []}

    from src.app.core.services import JwksService

    monkeypatch.setattr(JwksService, "fetch_jwks", _noop_fetch_jwks)
    return monkeypatch


class TestApplicationStartup:
    @pytest.mark.asyncio
    async def test_startup_initializes_redis_rate_limiter_when_enabled(
        self, neutralized_startup: pytest.MonkeyPatch
    ) -> None:
        """When Redis is enabled, startup constructs a Redis client and calls
        ``FastAPILimiter.init`` on it. We patch the lazy imports inside
        ``_initialize_rate_limiter`` so no real connection is attempted."""
        import src.app.api.http.app as application

        init_calls: list[object] = []

        class _FakeLimiter:
            @staticmethod
            async def init(redis: object) -> None:
                init_calls.append(redis)

        class _FakeRedisModule:
            @staticmethod
            def from_url(
                url: str,
                encoding: str | None = None,
                decode_responses: bool | None = None,
            ) -> object:
                return object()  # opaque sentinel

        # The route imports redis.asyncio and fastapi_limiter lazily inside
        # _initialize_rate_limiter — install fakes in sys.modules so those
        # in-function imports resolve to ours.
        fake_redis_pkg = types.ModuleType("redis")
        fake_redis_pkg.asyncio = _FakeRedisModule  # type: ignore[attr-defined]
        neutralized_startup.setitem(sys.modules, "redis", fake_redis_pkg)
        neutralized_startup.setitem(sys.modules, "redis.asyncio", _FakeRedisModule)

        fake_fastapi_limiter = types.ModuleType("fastapi_limiter")
        fake_fastapi_limiter.FastAPILimiter = _FakeLimiter  # type: ignore[attr-defined]
        neutralized_startup.setitem(
            sys.modules, "fastapi_limiter", fake_fastapi_limiter
        )

        # The default dev config already has redis enabled; no override needed.
        await application.startup()

        # The limiter was wired up against our fake Redis client.
        assert init_calls, "FastAPILimiter.init was never invoked"

        # And the broader dependency container is populated.
        deps = application.app.state.app_dependencies
        assert deps.auth_session_service is not None
        assert deps.user_session_service is not None
        assert deps.jwt_verify_service is not None

    @pytest.mark.asyncio
    async def test_startup_falls_back_to_local_limiter_when_redis_disabled(
        self, neutralized_startup: pytest.MonkeyPatch
    ) -> None:
        """With ``redis.enabled = False``, no Redis service is constructed,
        storage falls back to InMemoryStorage, and the local in-memory rate
        limiter takes over (``_activate_local_rate_limiter`` was invoked)."""
        import src.app.api.http.app as application
        from src.app.core.services.storage.memory import InMemoryStorage

        local_activated = {"called": False}
        original_activate = application._activate_local_rate_limiter

        def _spy_activate() -> None:
            local_activated["called"] = True
            original_activate()

        neutralized_startup.setattr(
            application, "_activate_local_rate_limiter", _spy_activate
        )

        # Mutate the live config in place, then restore. We can't go through
        # with_context here (see module docstring).
        original_redis_enabled = config.redis.enabled
        config.redis.enabled = False
        try:
            await application.startup()

            deps = application.app.state.app_dependencies
            assert isinstance(deps.app_storage, InMemoryStorage)
            assert deps.redis_service is None
            assert local_activated["called"]
        finally:
            config.redis.enabled = original_redis_enabled
