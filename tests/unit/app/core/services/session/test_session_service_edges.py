"""Edge-case coverage for AuthSessionService and UserSessionService.

The main test_session_service.py covers the happy paths and validation
flows. This file focuses on the error-recovery branches and the
update/validate/list code paths that the main suite skips.
"""

from __future__ import annotations

import time

import pytest

from src.app.core.models.session import AuthSession, UserSession
from src.app.core.security import hash_client_fingerprint
from src.app.core.services import (
    AuthSessionService,
    SessionStorage,
    UserSessionService,
)

# ---------- AuthSessionService.update_auth_session ----------


class TestUpdateAuthSession:
    @pytest.mark.asyncio
    async def test_unknown_session_raises(
        self, auth_session_service: AuthSessionService
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            await auth_session_service.update_auth_session(
                session_id="never-existed", extension_seconds=10
            )

    @pytest.mark.asyncio
    async def test_used_session_raises(
        self, auth_session_service: AuthSessionService
    ) -> None:
        session_id = await auth_session_service.create_auth_session(
            pkce_verifier="v",
            state="s",
            nonce="n",
            provider="default",
            return_to="/",
            client_fingerprint_hash="fp",
        )
        await auth_session_service.mark_auth_session_used(session_id)

        with pytest.raises(ValueError, match="already used"):
            await auth_session_service.update_auth_session(
                session_id=session_id, extension_seconds=10
            )

    @pytest.mark.asyncio
    async def test_expired_session_is_deleted_and_raises(
        self,
        session_storage: SessionStorage,
        auth_session_service: AuthSessionService,
    ) -> None:
        """A session that's already past its expiry on entry must be deleted
        as a defense, not refreshed."""
        now = int(time.time())
        expired = AuthSession(
            id="expired-id",
            pkce_verifier="v",
            state="s",
            nonce="n",
            provider="default",
            return_to="/",
            client_fingerprint_hash="fp",
            created_at=now - 7200,
            expires_at=now - 3600,
        )
        await session_storage.set(f"auth:{expired.id}", expired, 3600)

        with pytest.raises(ValueError, match="expired"):
            await auth_session_service.update_auth_session(
                session_id=expired.id, extension_seconds=60
            )

        # Defense: storage no longer has the expired session.
        assert await session_storage.get(f"auth:{expired.id}", AuthSession) is None

    @pytest.mark.asyncio
    async def test_negative_extension_expires_session(
        self, auth_session_service: AuthSessionService
    ) -> None:
        """A negative extension that pushes expiry into the past deletes the
        session as a side effect — used by tests to force expiry."""
        session_id = await auth_session_service.create_auth_session(
            pkce_verifier="v",
            state="s",
            nonce="n",
            provider="default",
            return_to="/",
            client_fingerprint_hash="fp",
        )

        await auth_session_service.update_auth_session(
            session_id=session_id, extension_seconds=-60
        )

        # Subsequent get returns None (storage cleaned up).
        assert await auth_session_service.get_auth_session(session_id) is None

    @pytest.mark.asyncio
    async def test_return_to_is_updated_and_sanitized(
        self, auth_session_service: AuthSessionService
    ) -> None:
        """update_auth_session re-sanitizes return_to: an external URL with no
        allowlist falls back to ``/``."""
        session_id = await auth_session_service.create_auth_session(
            pkce_verifier="v",
            state="s",
            nonce="n",
            provider="default",
            return_to="/dashboard",
            client_fingerprint_hash="fp",
        )

        # Sanitization rejects unknown absolute URLs and falls back to "/".
        updated = await auth_session_service.update_auth_session(
            session_id=session_id,
            return_to="https://evil.example.com/steal",
        )
        assert updated.return_to == "/"


# ---------- UserSessionService.update_user_session ----------


class TestUpdateUserSession:
    @pytest.mark.asyncio
    async def test_unknown_session_raises(
        self, user_session_service: UserSessionService
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            await user_session_service.update_user_session(
                session_id="never-existed", extension_seconds=10
            )

    @pytest.mark.asyncio
    async def test_token_update_persists(
        self, user_session_service: UserSessionService
    ) -> None:
        """Updating tokens writes new values back to storage."""
        session_id = await user_session_service.create_user_session(
            user_id="u-1",
            provider="default",
            client_fingerprint="fp",
            access_token="old-access",
            refresh_token="old-refresh",
        )

        await user_session_service.update_user_session(
            session_id=session_id,
            access_token="new-access",
            refresh_token="new-refresh",
            access_token_expires_at=int(time.time()) + 3600,
        )

        reloaded = await user_session_service.get_user_session(session_id)
        assert reloaded is not None
        assert reloaded.access_token == "new-access"
        assert reloaded.refresh_token == "new-refresh"

    @pytest.mark.asyncio
    async def test_extend_user_session_delegates_to_update(
        self, user_session_service: UserSessionService
    ) -> None:
        """extend_user_session is a thin wrapper around update_user_session."""
        session_id = await user_session_service.create_user_session(
            user_id="u-1",
            provider="default",
            client_fingerprint="fp",
            access_token="t",
        )
        before = await user_session_service.get_user_session(session_id)
        assert before is not None

        await user_session_service.extend_user_session(
            session_id, additional_seconds=600
        )

        after = await user_session_service.get_user_session(session_id)
        assert after is not None
        # Extension reset expires_at to now + 600.
        assert after.expires_at >= int(time.time()) + 590


# ---------- UserSessionService.validate_user_session ----------


class TestValidateUserSession:
    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_session(
        self, user_session_service: UserSessionService
    ) -> None:
        result = await user_session_service.validate_user_session(
            session_id="never-existed", client_fingerprint="fp"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_fingerprint_mismatch_deletes_session(
        self, user_session_service: UserSessionService
    ) -> None:
        """Defense against session hijacking: a fingerprint mismatch wipes the
        session, not just rejects the current request."""
        session_id = await user_session_service.create_user_session(
            user_id="u-1",
            provider="default",
            client_fingerprint="real-fingerprint",
            access_token="t",
        )

        result = await user_session_service.validate_user_session(
            session_id=session_id, client_fingerprint="attacker-fingerprint"
        )

        assert result is None
        assert await user_session_service.get_user_session(session_id) is None

    @pytest.mark.asyncio
    async def test_matching_fingerprint_returns_session(
        self, user_session_service: UserSessionService
    ) -> None:
        session_id = await user_session_service.create_user_session(
            user_id="u-1",
            provider="default",
            client_fingerprint="fp",
            access_token="t",
        )

        result = await user_session_service.validate_user_session(
            session_id=session_id, client_fingerprint="fp"
        )

        assert result is not None
        assert result.id == session_id
        # Fingerprint stored as a hash, not the raw value.
        assert result.client_fingerprint == hash_client_fingerprint("fp")


# ---------- UserSessionService.list_user_sessions filter ----------


class TestListUserSessions:
    @pytest.mark.asyncio
    async def test_filters_by_user_id(
        self, user_session_service: UserSessionService
    ) -> None:
        await user_session_service.create_user_session(
            user_id="alice",
            provider="default",
            client_fingerprint="fp",
            access_token="t",
        )
        await user_session_service.create_user_session(
            user_id="bob",
            provider="default",
            client_fingerprint="fp",
            access_token="t",
        )
        await user_session_service.create_user_session(
            user_id="alice",
            provider="default",
            client_fingerprint="fp",
            access_token="t",
        )

        alice_only = await user_session_service.list_user_sessions(user_id="alice")
        assert len(alice_only) == 2
        assert all(s.user_id == "alice" for s in alice_only)
