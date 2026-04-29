"""Tests for the session management/maintenance utilities.

These functions are used for operational concerns: counting in-flight
sessions, sweeping expired ones, and (in tests) clearing all sessions
between cases. They run against real session services backed by in-memory
storage; nothing is mocked.
"""

from __future__ import annotations

import time

from src.app.core.models.session import AuthSession
from src.app.core.services import (
    AuthSessionService,
    SessionStorage,
    UserSessionService,
)
from src.app.core.services.session.manage_sessions import (
    cleanup_expired_sessions,
    clear_all_sessions,
    count_active_sessions,
)


async def _seed_auth_session(
    auth_session_service: AuthSessionService, *, state: str
) -> str:
    return await auth_session_service.create_auth_session(
        pkce_verifier="verifier",
        state=state,
        nonce="nonce",
        provider="default",
        return_to="/",
        client_fingerprint_hash="fp",
    )


async def _seed_user_session(
    user_session_service: UserSessionService, *, user_id: str
) -> str:
    return await user_session_service.create_user_session(
        user_id=user_id,
        provider="default",
        client_fingerprint="fp",
        access_token="access",
        access_token_expires_at=0,
    )


class TestCountActiveSessions:
    async def test_zero_when_storage_empty(
        self,
        auth_session_service: AuthSessionService,
        user_session_service: UserSessionService,
    ) -> None:
        counts = await count_active_sessions(user_session_service, auth_session_service)
        assert counts == {"auth": 0, "user": 0}

    async def test_counts_auth_and_user_sessions_separately(
        self,
        auth_session_service: AuthSessionService,
        user_session_service: UserSessionService,
    ) -> None:
        await _seed_auth_session(auth_session_service, state="s1")
        await _seed_auth_session(auth_session_service, state="s2")
        await _seed_user_session(user_session_service, user_id="u1")

        counts = await count_active_sessions(user_session_service, auth_session_service)
        assert counts == {"auth": 2, "user": 1}


class TestCleanupExpiredSessions:
    async def test_removes_expired_auth_sessions(
        self,
        session_storage: SessionStorage,
        auth_session_service: AuthSessionService,
    ) -> None:
        """Sessions whose expires_at is in the past are deleted; live ones stay."""
        live_id = await _seed_auth_session(auth_session_service, state="live")

        # Inject an already-expired session directly into storage so cleanup
        # has something to find. (Going through update_auth_session would
        # delete-on-expire as a side effect.)
        now = int(time.time())
        expired = AuthSession(
            id="expired-session",
            pkce_verifier="v",
            state="expired",
            nonce="n",
            provider="default",
            return_to="/",
            client_fingerprint_hash="fp",
            created_at=now - 7200,
            expires_at=now - 3600,
        )
        await session_storage.set(f"auth:{expired.id}", expired, 3600)

        counts = await cleanup_expired_sessions(session_storage)

        assert counts["auth"] >= 1
        # Live session preserved.
        assert await auth_session_service.get_auth_session(live_id) is not None
        # Expired session removed from storage.
        assert await session_storage.get(f"auth:{expired.id}", AuthSession) is None

    async def test_returns_zero_counts_when_nothing_expired(
        self,
        session_storage: SessionStorage,
        auth_session_service: AuthSessionService,
        user_session_service: UserSessionService,
    ) -> None:
        await _seed_auth_session(auth_session_service, state="s1")
        await _seed_user_session(user_session_service, user_id="u1")

        counts = await cleanup_expired_sessions(session_storage)
        assert counts == {"auth": 0, "user": 0}


class TestClearAllSessions:
    """clear_all_sessions runs in the autouse reset fixture between tests, so
    its happy path is exercised on every test boundary. These cases verify
    its return shape and that it touches both session families."""

    async def test_clears_both_session_families(
        self,
        session_storage: SessionStorage,
        auth_session_service: AuthSessionService,
        user_session_service: UserSessionService,
    ) -> None:
        await _seed_auth_session(auth_session_service, state="s1")
        await _seed_user_session(user_session_service, user_id="u1")
        await _seed_user_session(user_session_service, user_id="u2")

        counts = await clear_all_sessions(session_storage)

        assert counts["auth"] == 1
        assert counts["user"] == 2
        # Storage truly empty afterwards.
        assert await count_active_sessions(
            user_session_service, auth_session_service
        ) == {"auth": 0, "user": 0}
