"""Tests for enhanced session service with security improvements."""

import time
from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.models.session import AuthSession, UserSession
from src.app.core.security import (
    generate_csrf_token,
    generate_nonce,
    validate_csrf_token,
)
from src.app.core.services import (
    AuthSessionService,
    OidcClientService,
    UserSessionService,
)
from src.app.core.services.jwt.jwt_utils import create_token_claims
from src.app.core.services.user.user_management import UserManagementService
from src.app.entities.core.user import User
from src.app.runtime.context import with_context


class TestSessionService:
    """Test session management functionality."""

    @pytest.mark.asyncio
    async def test_auth_session_lifecycle(
        self, auth_session_service: AuthSessionService
    ):
        """Test complete auth session lifecycle."""
        # Create session
        session_id = await auth_session_service.create_auth_session(
            nonce=generate_nonce(),
            client_fingerprint_hash="test_fingerprint",
            pkce_verifier="test-verifier",
            state="test-state",
            provider="google",
            return_to="/dashboard",
        )

        assert isinstance(session_id, str)

        # Retrieve session
        auth_session = await auth_session_service.get_auth_session(session_id)
        assert auth_session is not None
        assert isinstance(auth_session, AuthSession)
        assert auth_session.pkce_verifier == "test-verifier"
        assert auth_session.state == "test-state"

        # Delete session
        await auth_session_service.delete_auth_session(session_id)
        assert await auth_session_service.get_auth_session(session_id) is None

    @pytest.mark.asyncio
    async def test_auth_session_expiry(self, auth_session_service: AuthSessionService):
        """Test auth session expiry handling."""
        session_id = await auth_session_service.create_auth_session(
            nonce=generate_nonce(),
            client_fingerprint_hash="test_fingerprint",
            pkce_verifier="test-verifier",
            state="test-state",
            provider="google",
            return_to="/dashboard",
        )

        # Manually expire session
        auth_session = await auth_session_service.get_auth_session(session_id)
        assert auth_session is not None
        await auth_session_service.update_auth_session(
            session_id=session_id, extension_seconds=-10
        )

        # Should return None and clean up
        result = await auth_session_service.get_auth_session(session_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_user_session_lifecycle(
        self, user_session_service: UserSessionService
    ):
        """Test complete user session lifecycle."""
        user_id = "12345678-1234-5678-9abc-123456789012"

        # Create session
        session_id = await user_session_service.create_user_session(
            client_fingerprint="test_fingerprint",
            user_id=user_id,
            provider="google",
            refresh_token="refresh-123",
            access_token="access-456",
            access_token_expires_at=int(time.time()) + 3600,
        )

        assert isinstance(session_id, str)

        # Retrieve session
        user_session = await user_session_service.get_user_session(session_id)
        assert user_session is not None
        assert isinstance(user_session, UserSession)
        assert user_session.user_id == user_id

        # Delete session
        await user_session_service.delete_user_session(session_id)
        assert await user_session_service.get_user_session(session_id) is None

    @pytest.mark.asyncio
    async def test_user_session_updates_last_accessed(
        self, user_session_service: UserSessionService
    ):
        """Test user session last_accessed_at updates."""
        user_id = "12345678-1234-5678-9abc-123456789012"
        base_time = int(time.time())

        session_id = await user_session_service.create_user_session(
            client_fingerprint="test_fingerprint",
            user_id=user_id,
            provider="google",
            refresh_token="refresh-123",
            access_token="access-456",
            access_token_expires_at=base_time + 3600,
        )

        # Get initial access time
        user_session = await user_session_service.get_user_session(session_id)
        assert user_session is not None
        initial_time = user_session.last_accessed_at

        # Mock time to return later time for next access
        with patch("time.time", return_value=base_time + 2):
            user_session = await user_session_service.get_user_session(session_id)
            assert user_session is not None
            updated_time = user_session.last_accessed_at
            assert updated_time > initial_time

    @pytest.mark.asyncio
    async def test_provision_user_from_claims_new_user(
        self, user_management_service: UserManagementService
    ):
        """Test JIT user provisioning for new user."""
        claims_dict = {
            "iss": "https://new-provider.test",
            "sub": "new-user-67890",
            "email": "newuser@example.com",
            "given_name": "New",
            "family_name": "User",
        }

        claims = create_token_claims(token="dummy-token", claims=claims_dict)

        user = await user_management_service.provision_user_from_claims(claims)

        assert isinstance(user, User)
        assert user.email == "newuser@example.com"
        assert user.first_name == "New"
        assert user.last_name == "User"

    @pytest.mark.asyncio
    async def test_provision_user_from_claims_existing_user(
        self,
        user_management_service: UserManagementService,
        session,
        test_user,
        test_user_identity,
    ):
        """Test JIT user provisioning returns existing user with updated info."""
        # Populate session with the specific test fixtures
        from src.app.entities.core.user import UserRepository
        from src.app.entities.core.user_identity import UserIdentityRepository

        user_repo = UserRepository(session)
        identity_repo = UserIdentityRepository(session)

        # Create the test user and identity in the session
        user_repo.create(test_user)
        identity_repo.create(test_user_identity)
        session.commit()

        claims_dict = {
            "iss": test_user_identity.issuer,
            "sub": test_user_identity.subject,
            "email": "updated@example.com",
            "given_name": "Updated",
            "family_name": "User",
        }

        claims = create_token_claims(token="dummy-token", claims=claims_dict)

        with patch.object(session, "close", return_value=None):
            user = await user_management_service.provision_user_from_claims(claims)

            # Should return existing user with updated info
            assert user.id == test_user.id
            assert user.email == "updated@example.com"
            assert user.first_name == "Updated"

    def test_csrf_token_generation_and_validation(self):
        """Test CSRF token generation and validation."""
        session_id = "test-session-123"

        # Generate token
        csrf_token = generate_csrf_token(session_id)
        assert isinstance(csrf_token, str) and len(csrf_token) > 0

        # Should validate correctly
        assert validate_csrf_token(session_id, csrf_token) is True

        # Should reject invalid token
        assert validate_csrf_token(session_id, "invalid-token") is False

        # Should reject None
        assert validate_csrf_token(session_id, None) is False

    def test_csrf_token_different_sessions(self):
        """Test CSRF token validation across different sessions."""
        session_id1 = "session-123"
        session_id2 = "session-456"

        # Generate token for first session
        csrf_token = generate_csrf_token(session_id1)

        # Should validate for correct session
        assert validate_csrf_token(session_id1, csrf_token) is True

        # Should reject for different session
        assert validate_csrf_token(session_id2, csrf_token) is False

    @pytest.mark.asyncio
    async def test_auth_session_cleanup_on_expiry_check(
        self, auth_session_service: AuthSessionService
    ):
        """Test that expired sessions are cleaned up when accessed."""
        # Create multiple sessions
        session_ids = []
        for i in range(3):
            session_id = await auth_session_service.create_auth_session(
                nonce=generate_nonce(),
                client_fingerprint_hash="test_fingerprint",
                pkce_verifier=f"verifier-{i}",
                state=f"state-{i}",
                provider="google",
                return_to="/dashboard",
            )
            session_ids.append(session_id)

        # Verify all sessions exist
        for session_id in session_ids:
            assert await auth_session_service.get_auth_session(session_id) is not None

        # Expire the middle session
        middle_session = await auth_session_service.get_auth_session(session_ids[1])
        assert middle_session is not None
        await auth_session_service.update_auth_session(
            session_id=middle_session.id, extension_seconds=-10
        )

        # Access the expired session - should be cleaned up
        assert await auth_session_service.get_auth_session(session_ids[1]) is None

        # Other sessions should remain
        assert await auth_session_service.get_auth_session(session_ids[0]) is not None
        assert await auth_session_service.get_auth_session(session_ids[2]) is not None

    @pytest.mark.asyncio
    async def test_user_session_expiry_handling(
        self, user_session_service: UserSessionService
    ):
        """Test user session expiry scenarios."""
        user_id = "12345678-1234-5678-9abc-123456789012"

        session_id = await user_session_service.create_user_session(
            client_fingerprint="test_fingerprint",
            user_id=user_id,
            provider="google",
            refresh_token="refresh-123",
            access_token="access-456",
            access_token_expires_at=int(time.time())
            + 3600,  # This is access_token_expires_at
        )

        # Manually expire the session to test expiry handling
        user_session = await user_session_service.get_user_session(session_id)
        assert user_session is not None
        await user_session_service.update_user_session(
            session_id=session_id, extension_seconds=-10
        )

        # Should return None for expired session due to cleanup logic
        result = await user_session_service.get_user_session(session_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_session_isolation(
        self,
        auth_session_service: AuthSessionService,
        user_session_service: UserSessionService,
    ):
        """Test that sessions are properly isolated from each other."""
        # Create auth sessions
        auth_id1 = await auth_session_service.create_auth_session(
            nonce=generate_nonce(),
            client_fingerprint_hash="test_fingerprint",
            pkce_verifier="auth-verifier-1",
            state="auth-state-1",
            provider="google",
            return_to="/dashboard",
        )

        auth_id2 = await auth_session_service.create_auth_session(
            nonce=generate_nonce(),
            client_fingerprint_hash="test_fingerprint",
            pkce_verifier="auth-verifier-2",
            state="auth-state-2",
            provider="github",
            return_to="/profile",
        )

        # Create user sessions
        user_id1 = "11111111-1111-1111-1111-111111111111"
        user_id2 = "22222222-2222-2222-2222-222222222222"

        user_session_id1 = await user_session_service.create_user_session(
            client_fingerprint="test_fingerprint",
            user_id=user_id1,
            provider="google",
            refresh_token="refresh-1",
            access_token="access-1",
            access_token_expires_at=int(time.time()) + 3600,
        )

        user_session_id2 = await user_session_service.create_user_session(
            client_fingerprint="test_fingerprint",
            user_id=user_id2,
            provider="github",
            refresh_token="refresh-2",
            access_token="access-2",
            access_token_expires_at=int(time.time()) + 3600,
        )

        # Verify isolation - each session returns only its own data
        auth1 = await auth_session_service.get_auth_session(auth_id1)
        auth2 = await auth_session_service.get_auth_session(auth_id2)

        assert auth1 is not None and auth1.pkce_verifier == "auth-verifier-1"
        assert auth1 is not None and auth1.provider == "google"
        assert auth2 is not None and auth2.pkce_verifier == "auth-verifier-2"
        assert auth2 is not None and auth2.provider == "github"

        user1 = await user_session_service.get_user_session(user_session_id1)
        user2 = await user_session_service.get_user_session(user_session_id2)

        assert user1 is not None and user1.user_id == user_id1
        assert user1 is not None and user1.provider == "google"
        assert user2 is not None and user2.user_id == user_id2
        assert user2 is not None and user2.provider == "github"

        # Cross-session access should return None
        assert await auth_session_service.get_auth_session(user_session_id1) is None
        assert await user_session_service.get_user_session(auth_id1) is None

    @pytest.mark.asyncio
    async def test_session_id_collision_resistance(
        self, auth_session_service: AuthSessionService
    ):
        """Test that session IDs are sufficiently random to avoid collisions."""
        # Create many sessions and verify no ID collisions
        session_ids = set()
        for _ in range(1000):
            session_id = await auth_session_service.create_auth_session(
                client_fingerprint_hash="test_fingerprint",
                nonce=generate_nonce(),
                pkce_verifier="verifier",
                state="state",
                provider="test",
                return_to="/",
            )
            assert session_id not in session_ids, "Session ID collision detected"
            session_ids.add(session_id)

        # Clean up
        for session_id in session_ids:
            await auth_session_service.delete_auth_session(session_id)

    @pytest.mark.asyncio
    async def test_refresh_user_session_success(
        self,
        auth_test_config,
        provider,
        user_session_service: UserSessionService,
        oidc_client_service: OidcClientService,
    ):
        """Test successful user session refresh."""
        user_id = "12345678-1234-5678-9abc-123456789012"
        auth_test_config.oidc.refresh_tokens.enabled = True
        auth_test_config.oidc.refresh_tokens.persist_in_session_store = True

        with with_context(config_override=auth_test_config):
            # Create initial session
            session_id = await user_session_service.create_user_session(
                client_fingerprint="test_fingerprint",
                user_id=user_id,
                provider=provider,
                refresh_token="old-refresh-token",
                access_token="old-access-token",
                access_token_expires_at=int(time.time()) + 3600,
            )

            # Mock the OIDC client service
            with patch.object(
                oidc_client_service, "refresh_access_token"
            ) as mock_refresh:
                from src.app.core.services.oidc_client_service import TokenResponse

                mock_refresh.return_value = TokenResponse(
                    access_token="new-access-token",
                    token_type="Bearer",
                    expires_in=3600,
                    refresh_token="new-refresh-token",
                )

                # Refresh the session
                new_session_id = await user_session_service.refresh_user_session(
                    session_id, oidc_client_service
                )

                # Should return new session ID
                assert isinstance(new_session_id, str)
                assert new_session_id != session_id

                # Old session should be gone
                assert await user_session_service.get_user_session(session_id) is None

                # New session should exist with updated tokens
                new_session = await user_session_service.get_user_session(
                    new_session_id
                )
                assert new_session is not None
                assert new_session.access_token == "new-access-token"
                assert new_session.refresh_token == "new-refresh-token"

    @pytest.mark.asyncio
    async def test_refresh_user_session_disabled_policy(
        self,
        auth_test_config,
        user_session_service: UserSessionService,
        oidc_client_service: OidcClientService,
    ):
        auth_test_config.oidc.refresh_tokens.enabled = False
        user_id = "12345678-1234-5678-9abc-123456789012"

        with with_context(config_override=auth_test_config):
            session_id = await user_session_service.create_user_session(
                client_fingerprint="test_fingerprint",
                user_id=user_id,
                provider="google",
                refresh_token="refresh-token",
                access_token="access-token",
                access_token_expires_at=int(time.time()) + 3600,
            )

            with pytest.raises(ValueError, match="Refresh tokens are disabled"):
                await user_session_service.refresh_user_session(
                    session_id, oidc_client_service
                )

    @pytest.mark.asyncio
    async def test_refresh_user_session_lifetime_enforced(
        self,
        auth_test_config,
        user_session_service: UserSessionService,
        oidc_client_service: OidcClientService,
    ):
        auth_test_config.oidc.refresh_tokens.enabled = True
        auth_test_config.oidc.refresh_tokens.max_session_lifetime_seconds = 60
        user_id = "12345678-1234-5678-9abc-123456789012"

        with with_context(config_override=auth_test_config):
            session_id = await user_session_service.create_user_session(
                client_fingerprint="test_fingerprint",
                user_id=user_id,
                provider="google",
                refresh_token="refresh-token",
                access_token="access-token",
                access_token_expires_at=int(time.time()) + 3600,
            )
            storage = user_session_service._storage  # test-only access
            stored_session = await storage.get(f"user:{session_id}", UserSession)
            assert stored_session is not None
            stored_session.created_at -= 120
            await storage.set(
                f"user:{session_id}",
                stored_session,
                auth_test_config.app.session_max_age,
            )

            with pytest.raises(ValueError, match="Refresh token lifetime exceeded"):
                await user_session_service.refresh_user_session(
                    session_id, oidc_client_service
                )

    @pytest.mark.asyncio
    async def test_refresh_user_session_not_found(
        self,
        auth_test_config,
        user_session_service: UserSessionService,
        oidc_client_service: OidcClientService,
    ):
        """Test refreshing non-existent session raises error."""
        auth_test_config.oidc.refresh_tokens.enabled = True
        with with_context(config_override=auth_test_config):
            with pytest.raises(ValueError, match="Session not found or expired"):
                await user_session_service.refresh_user_session(
                    "nonexistent-session", oidc_client_service
                )

    @pytest.mark.asyncio
    async def test_refresh_user_session_no_refresh_token(
        self,
        auth_test_config,
        user_session_service: UserSessionService,
        oidc_client_service: OidcClientService,
    ):
        """Test refreshing session without refresh token raises error."""
        user_id = "12345678-1234-5678-9abc-123456789012"

        auth_test_config.oidc.refresh_tokens.enabled = True

        with with_context(config_override=auth_test_config):
            session_id = await user_session_service.create_user_session(
                client_fingerprint="test_fingerprint",
                user_id=user_id,
                provider="google",
                refresh_token=None,  # No refresh token
                access_token="access-token",
                access_token_expires_at=int(time.time()) + 3600,
            )

            with pytest.raises(ValueError, match="No refresh token available"):
                await user_session_service.refresh_user_session(
                    session_id, oidc_client_service
                )

    @pytest.mark.asyncio
    async def test_refresh_user_session_refresh_fails(
        self,
        auth_test_config,
        user_session_service: UserSessionService,
        oidc_client_service: OidcClientService,
    ):
        """Test refresh session when token refresh fails."""
        user_id = "12345678-1234-5678-9abc-123456789012"
        auth_test_config.oidc.refresh_tokens.enabled = True

        with with_context(config_override=auth_test_config):
            session_id = await user_session_service.create_user_session(
                client_fingerprint="test_fingerprint",
                user_id=user_id,
                provider="google",
                refresh_token="refresh-token",
                access_token="access-token",
                access_token_expires_at=int(time.time()) + 3600,
            )

            # Mock refresh to fail
            with patch.object(
                oidc_client_service, "refresh_access_token"
            ) as mock_refresh:
                mock_refresh.side_effect = Exception("Token refresh failed")

                with pytest.raises(ValueError, match="Token refresh failed"):
                    await user_session_service.refresh_user_session(
                        session_id, oidc_client_service
                    )

                # Session should be cleaned up on failure
                assert await user_session_service.get_user_session(session_id) is None

    def test_csrf_token_malformed_handling(self):
        """Test validating malformed CSRF token doesn't crash."""
        session_id = "test-session-malformed"

        # Should handle empty/None gracefully
        is_valid = validate_csrf_token(session_id, "")
        assert is_valid is False

        is_valid = validate_csrf_token(session_id, None)
        assert is_valid is False

        # Should handle malformed tokens
        is_valid = validate_csrf_token(session_id, "invalid-format")
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_session_memory_management(
        self,
        auth_session_service: AuthSessionService,
        user_session_service: UserSessionService,
    ):
        """Test that session cleanup prevents memory leaks."""
        initial_auth_count = len(await auth_session_service.list_auth_sessions())
        initial_user_count = len(await user_session_service.list_user_sessions())

        # Create and immediately delete many sessions
        for i in range(50):
            # Auth sessions
            auth_id = await auth_session_service.create_auth_session(
                nonce=generate_nonce(),
                client_fingerprint_hash="test_fingerprint",
                pkce_verifier=f"verifier-{i}",
                state=f"state-{i}",
                provider="test",
                return_to="/test",
            )
            await auth_session_service.delete_auth_session(auth_id)

            # User sessions
            user_session_id = await user_session_service.create_user_session(
                client_fingerprint="test_fingerprint",
                user_id=f"user-{i}",
                provider="test",
                refresh_token=f"refresh-{i}",
                access_token=f"access-{i}",
                access_token_expires_at=int(time.time()) + 3600,
            )
            await user_session_service.delete_user_session(user_session_id)

        # Memory should be cleaned up
        final_auth_count = len(await auth_session_service.list_auth_sessions())
        final_user_count = len(await user_session_service.list_user_sessions())

        assert final_auth_count == initial_auth_count
        assert final_user_count == initial_user_count

    @pytest.mark.asyncio
    async def test_concurrent_session_operations(
        self, user_session_service: UserSessionService
    ):
        """Test that concurrent session operations don't interfere."""
        user_id = "12345678-1234-5678-9abc-123456789012"

        # Create multiple user sessions for the same user
        session_ids = []
        for i in range(3):
            session_id = await user_session_service.create_user_session(
                client_fingerprint=f"fingerprint-{i}",
                user_id=user_id,
                provider=f"provider-{i}",
                refresh_token=f"refresh-{i}",
                access_token=f"access-{i}",
                access_token_expires_at=int(time.time()) + 3600,
            )
            session_ids.append(session_id)

        # Verify all sessions are independent
        for i, session_id in enumerate(session_ids):
            user_session = await user_session_service.get_user_session(session_id)
            assert user_session is not None
            assert user_session.user_id == user_id
            assert user_session.provider == f"provider-{i}"
            assert user_session.refresh_token == f"refresh-{i}"

        # Delete middle session
        await user_session_service.delete_user_session(session_ids[1])

        # Verify other sessions are unaffected
        assert await user_session_service.get_user_session(session_ids[0]) is not None
        assert await user_session_service.get_user_session(session_ids[1]) is None
        assert await user_session_service.get_user_session(session_ids[2]) is not None

        # Clean up
        await user_session_service.delete_user_session(session_ids[0])
        await user_session_service.delete_user_session(session_ids[2])


class TestSessionServiceNew:
    """Test enhanced session service functionality."""

    @pytest.mark.asyncio
    async def test_create_auth_session(self, auth_session_service: AuthSessionService):
        """Test creating auth session with security features."""

        assert len(await auth_session_service.list_auth_sessions()) == 0
        session_id = await auth_session_service.create_auth_session(
            pkce_verifier="test_verifier",
            state="test_state",
            nonce="test_nonce",
            provider="keycloak",
            return_to="/dashboard",
            client_fingerprint_hash="test_fingerprint",
        )

        assert isinstance(session_id, str)
        assert len(session_id) > 0
        assert len(await auth_session_service.list_auth_sessions()) == 1
        assert await auth_session_service.get_auth_session(session_id) is not None

    @pytest.mark.asyncio
    async def test_validate_auth_session(
        self, test_auth_session: AuthSession, auth_session_service: AuthSessionService
    ):
        """Test auth session validation with security checks."""

        session_id = await auth_session_service.create_auth_session(
            pkce_verifier="test_verifier",
            state="test_state",
            nonce="test_nonce",
            provider="keycloak",
            return_to="/dashboard",
            client_fingerprint_hash="test_fingerprint",
        )

        # Test successful validation
        result = await auth_session_service.validate_auth_session(
            session_id=session_id,
            state="test_state",
            client_fingerprint_hash="test_fingerprint",
        )

        assert result is not None
        assert result.state == "test_state"
        assert result.client_fingerprint_hash == "test_fingerprint"
        assert result.id == session_id

    @pytest.mark.asyncio
    async def test_validate_auth_session_failures(
        self, test_auth_session: AuthSession, auth_session_service: AuthSessionService
    ):
        """Test auth session validation failure scenarios."""
        with (
            patch.object(auth_session_service, "get_auth_session") as mock_get_auth,
            patch.object(auth_session_service, "delete_auth_session") as mock_delete,
        ):
            # Test 1: Session not found
            mock_get_auth.return_value = None
            result = await auth_session_service.validate_auth_session(
                "nonexistent", "state", "fingerprint"
            )
            assert result is None

            # Test 2: Wrong state (CSRF failure)
            mock_get_auth.return_value = test_auth_session
            result = await auth_session_service.validate_auth_session(
                "test_session", "wrong_state", test_auth_session.client_fingerprint_hash
            )
            assert result is None
            mock_delete.assert_called_with("test_session")

            # Test 3: Wrong client fingerprint
            mock_delete.reset_mock()
            mock_get_auth.return_value = test_auth_session
            result = await auth_session_service.validate_auth_session(
                "test_session", test_auth_session.state, "wrong_fingerprint"
            )
            assert result is None
            mock_delete.assert_called_with("test_session")

    @pytest.mark.asyncio
    async def test_create_user_session(self, user_session_service: UserSessionService):
        """Test creating user session with security features."""

        assert len(await user_session_service.list_user_sessions()) == 0
        session_id = await user_session_service.create_user_session(
            user_id="user-123",
            provider="keycloak",
            client_fingerprint="test_fingerprint",
            access_token="access_token",
            refresh_token="refresh_token",
            access_token_expires_at=1234567890,
        )

        assert len(await user_session_service.list_user_sessions()) == 1
        assert await user_session_service.get_user_session(session_id) is not None
        assert isinstance(session_id, str)
        assert len(session_id) > 0

    def test_csrf_token_generation(self):
        """Test CSRF token generation and validation."""
        session_id = "test_session"

        # Generate token
        csrf_token = generate_csrf_token(session_id)
        assert isinstance(csrf_token, str)
        assert len(csrf_token) > 0

        # Validate token
        is_valid = validate_csrf_token(session_id, csrf_token)
        assert is_valid is True

        # Test invalid token
        is_valid = validate_csrf_token(session_id, "invalid_token")
        assert is_valid is False

        # Test None token
        is_valid = validate_csrf_token(session_id, None)
        assert is_valid is False
