"""Tests for enhanced session models."""

import time
from unittest.mock import patch

import pytest

from src.app.core.models.session import AuthSession, TokenClaims, UserSession
from src.app.core.security import hash_client_fingerprint


class TestAuthSession:
    """Test AuthSession model."""

    def test_create_auth_session(
        self,
        test_auth_session,
    ):
        """Test successful creation of an auth session."""
        session = test_auth_session

        assert session.id == "auth-session-123"
        assert session.pkce_verifier == "test-pkce-verifier"
        assert session.state == "test-state-parameter"
        assert session.nonce == "test-nonce-value"
        assert session.provider == "default"
        assert session.return_to == "/dashboard"
        assert session.client_fingerprint_hash == hash_client_fingerprint(
            "testclient", "testclient"
        )
        assert not session.used
        assert session.expires_at > session.created_at

    def test_auth_session_expiration(self, test_auth_session):
        """Test auth session expiration check."""
        session = test_auth_session

        # Check initial state
        assert not session.is_expired()

        # Force expiration
        session.expires_at = session.created_at - 1  # Already expired

        assert session.is_expired()

    def test_auth_session_mark_used(self, test_auth_session):
        """Test marking session as used."""
        session = test_auth_session

        assert not session.used
        session.mark_used()
        assert session.used


class TestUserSession:
    """Test UserSession model."""

    def test_create_user_session(self, test_user_session, test_user):
        """Test successful creation of a user session."""
        session = test_user_session

        assert session.id == "user-session-456"
        assert session.user_id == test_user.id
        assert session.provider == "default"
        assert session.client_fingerprint == hash_client_fingerprint(
            "testclient", "testclient"
        )
        assert session.refresh_token == "mock-refresh-token"
        assert session.access_token == "mock-access-token"
        assert session.expires_at > session.created_at

    def test_user_session_expiration(self, test_user_session: UserSession):
        """Test user session expiration check."""
        session = test_user_session

        # Check initial state
        assert not session.is_expired()

        # Force expiration
        session.expires_at = session.created_at - 1  # Already expired

        assert session.is_expired()

    def test_user_session_update_access(self, test_user_session: UserSession):
        """Test updating last access time."""

        session = test_user_session
        original_time = session.last_accessed_at

        updated_time = original_time + 2000

        with patch("time.time", return_value=updated_time):
            session.update_access()

        assert session.last_accessed_at > original_time
        assert session.last_accessed_at == updated_time

    def test_user_session_rotate_id(self, test_user_session: UserSession):
        """Test session ID rotation."""

        session = test_user_session
        initial_time = session.last_accessed_at
        rotation_time = initial_time + 1000

        with patch("time.time", return_value=rotation_time):
            session.rotate_session_id("new-id")

        assert session.id == "new-id"
        assert session.last_accessed_at > initial_time
        assert session.last_accessed_at == rotation_time

    def test_user_session_update_tokens(self, test_user_session: UserSession):
        """Test updating token information."""
        session = test_user_session
        initial_time = session.last_accessed_at
        update_time = initial_time + 1000

        with patch("time.time", return_value=update_time):
            session.update_tokens(
                access_token="new-access",
                refresh_token="new-refresh",
                access_token_expires_at=int(time.time()) + 7200,
            )

        assert session.access_token == "new-access"
        assert session.refresh_token == "new-refresh"
        assert session.last_accessed_at > initial_time
        assert session.last_accessed_at == update_time


class TestTokenClaims:
    """Test TokenClaims model."""

    def test_create_from_jwt_payload(self):
        """Test creating TokenClaims from JWT payload."""
        payload = {
            "iss": "https://auth.example.com",
            "sub": "user-123",
            "aud": "my-client",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "nonce": "test-nonce",
            "email": "user@example.com",
            "name": "Test User",
            "custom_claim": "custom_value",
        }

        claims = TokenClaims.from_jwt_payload(payload)

        assert claims.issuer == "https://auth.example.com"
        assert claims.subject == "user-123"
        assert claims.audience == "my-client"
        assert claims.nonce == "test-nonce"
        assert claims.email == "user@example.com"
        assert claims.name == "Test User"
        assert claims.custom_claims["custom_claim"] == "custom_value"

    def test_validate_nonce(self):
        """Test nonce validation."""
        claims = TokenClaims(
            issuer="issuer",
            subject="subject",
            audience="audience",
            expires_at=int(time.time()) + 3600,
            issued_at=int(time.time()),
            nonce="correct-nonce",
        )

        assert claims.validate_nonce("correct-nonce")
        assert not claims.validate_nonce("wrong-nonce")

    def test_validate_audience_string(self):
        """Test audience validation with string audience."""
        claims = TokenClaims(
            issuer="issuer",
            subject="subject",
            audience="my-client",
            expires_at=int(time.time()) + 3600,
            issued_at=int(time.time()),
        )

        assert claims.validate_audience(["my-client", "other-client"])
        assert not claims.validate_audience(["different-client"])

    def test_validate_audience_list(self):
        """Test audience validation with list audience."""
        claims = TokenClaims(
            issuer="issuer",
            subject="subject",
            audience=["my-client", "another-client"],
            expires_at=int(time.time()) + 3600,
            issued_at=int(time.time()),
        )

        assert claims.validate_audience(["my-client"])
        assert claims.validate_audience(["another-client"])
        assert claims.validate_audience(["my-client", "third-client"])
        assert not claims.validate_audience(["different-client"])

    def test_token_expiration(self):
        """Test token expiration validation."""
        # Expired token
        expired_claims = TokenClaims(
            issuer="issuer",
            subject="subject",
            audience="audience",
            expires_at=int(time.time()) - 100,  # Expired 100 seconds ago
            issued_at=int(time.time()) - 3600,
        )

        assert expired_claims.is_expired()
        assert expired_claims.is_expired(clock_skew=50)  # Still expired with skew

        # Valid token
        valid_claims = TokenClaims(
            issuer="issuer",
            subject="subject",
            audience="audience",
            expires_at=int(time.time()) + 3600,
            issued_at=int(time.time()),
        )

        assert not valid_claims.is_expired()

    def test_token_not_yet_valid(self):
        """Test token not-yet-valid validation."""
        future_time = int(time.time()) + 3600

        # Token not yet valid
        future_claims = TokenClaims(
            issuer="issuer",
            subject="subject",
            audience="audience",
            expires_at=future_time + 3600,
            issued_at=future_time,
            not_before=future_time,  # Not valid until future time
        )

        assert future_claims.is_not_yet_valid()
        assert future_claims.is_not_yet_valid(clock_skew=1800)  # Still not valid

        # Valid token (no nbf)
        valid_claims = TokenClaims(
            issuer="issuer",
            subject="subject",
            audience="audience",
            expires_at=int(time.time()) + 3600,
            issued_at=int(time.time()),
        )

        assert not valid_claims.is_not_yet_valid()

    def test_token_with_roles_and_scopes(self):
        """Test token with authorization claims."""
        payload = {
            "iss": "issuer",
            "sub": "subject",
            "aud": "audience",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "scope": "openid profile email",
            "roles": ["admin", "user"],
            "groups": ["developers", "staff"],
        }

        claims = TokenClaims.from_jwt_payload(payload)

        assert claims.scope == "openid profile email"
        assert claims.roles == ["admin", "user"]
        assert claims.groups == ["developers", "staff"]
