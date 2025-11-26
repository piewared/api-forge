"""Tests for security utilities."""

import time
from unittest.mock import patch

import pytest

from src.app.core.security import (
    generate_csrf_token,
    generate_nonce,
    generate_pkce_pair,
    generate_secure_token,
    generate_state,
    hash_client_fingerprint,
    sanitize_return_url,
    validate_client_fingerprint,
    validate_csrf_token,
)


class TestTokenGeneration:
    """Test secure token generation functions."""

    def test_generate_secure_token_default_length(self):
        """Test default token generation."""
        token = generate_secure_token()

        # Should be non-empty string
        assert isinstance(token, str)
        assert len(token) > 0

        # Should be URL-safe (no padding)
        assert "=" not in token
        assert "+" not in token
        assert "/" not in token

    def test_generate_secure_token_custom_length(self):
        """Test token generation with custom length."""
        token = generate_secure_token(16)

        # Length should be roughly 4/3 of input bytes (base64 encoding)
        # 16 bytes = ~22 chars (without padding)
        assert len(token) >= 20
        assert len(token) <= 25

    def test_generate_secure_token_uniqueness(self):
        """Test that tokens are unique."""
        tokens = [generate_secure_token() for _ in range(100)]
        assert len(set(tokens)) == 100  # All unique

    def test_generate_nonce(self):
        """Test nonce generation."""
        nonce = generate_nonce()

        assert isinstance(nonce, str)
        assert len(nonce) > 40  # 32 bytes = ~43 chars

        # Should be unique
        nonce2 = generate_nonce()
        assert nonce != nonce2

    def test_generate_state(self):
        """Test state generation."""
        state = generate_state()

        assert isinstance(state, str)
        assert len(state) > 40  # 32 bytes = ~43 chars

        # Should be unique
        state2 = generate_state()
        assert state != state2

    def test_generate_pkce_pair(self):
        """Test PKCE verifier and challenge generation."""
        verifier, challenge = generate_pkce_pair()

        # Both should be strings
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)

        # Should be different
        assert verifier != challenge

        # Should be URL-safe
        assert "=" not in verifier
        assert "=" not in challenge

        # Challenge should be SHA256 of verifier
        import base64
        import hashlib

        expected_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )

        assert challenge == expected_challenge


class TestCSRFTokens:
    """Test CSRF token generation and validation."""

    def test_generate_csrf_token(self):
        """Test CSRF token generation."""
        with patch("src.app.runtime.context.get_config") as mock_config:
            mock_config.return_value.app.session_signing_secret = "test-secret"

            token = generate_csrf_token("session-123")

            assert isinstance(token, str)
            assert ":" in token  # Should contain timestamp

            # Should be deterministic for same inputs
            token2 = generate_csrf_token("session-123")
            assert token == token2

    def test_generate_csrf_token_custom_timestamp(self):
        """Test CSRF token with custom timestamp."""
        with patch("src.app.runtime.context.get_config") as mock_config:
            mock_config.return_value.app.session_signing_secret = "test-secret"

            token1 = generate_csrf_token("session-123", 1000)
            token2 = generate_csrf_token("session-123", 2000)

            assert token1 != token2

    def test_validate_csrf_token_success(self):
        """Test successful CSRF token validation."""
        with patch("src.app.runtime.context.get_config") as mock_config:
            mock_config.return_value.app.session_signing_secret = "test-secret"

            token = generate_csrf_token("session-123")
            assert validate_csrf_token("session-123", token) is True

    def test_validate_csrf_token_wrong_session(self):
        """Test CSRF token validation with wrong session."""
        with patch("src.app.runtime.context.get_config") as mock_config:
            mock_config.return_value.app.session_signing_secret = "test-secret"

            token = generate_csrf_token("session-123")
            assert validate_csrf_token("session-456", token) is False

    def test_validate_csrf_token_none(self):
        """Test CSRF token validation with None token."""
        assert validate_csrf_token("session-123", None) is False

    def test_validate_csrf_token_malformed(self):
        """Test CSRF token validation with malformed token."""
        assert validate_csrf_token("session-123", "invalid") is False
        assert validate_csrf_token("session-123", "no-colon") is False

    def test_validate_csrf_token_expired(self):
        """Test CSRF token validation with expired token."""
        with patch("src.app.runtime.context.get_config") as mock_config:
            mock_config.return_value.app.session_signing_secret = "test-secret"

            # Generate token from 25 hours ago
            old_timestamp = int(time.time() // 3600) - 25
            token = generate_csrf_token("session-123", old_timestamp)

            assert validate_csrf_token("session-123", token, max_age_hours=24) is False

    def test_validate_csrf_token_custom_max_age(self):
        """Test CSRF token validation with custom max age."""
        with patch("src.app.runtime.context.get_config") as mock_config:
            mock_config.return_value.app.session_signing_secret = "test-secret"

            # Generate token from 2 hours ago
            old_timestamp = int(time.time() // 3600) - 2
            token = generate_csrf_token("session-123", old_timestamp)

            # Should fail with 1 hour max age
            assert validate_csrf_token("session-123", token, max_age_hours=1) is False

            # Should pass with 3 hour max age
            assert validate_csrf_token("session-123", token, max_age_hours=3) is True


class TestReturnUrlSanitization:
    """Test return URL sanitization."""

    def test_sanitize_return_url_none(self):
        """Test sanitization with None input."""
        result = sanitize_return_url(None)
        assert result == "/"

    def test_sanitize_return_url_empty(self):
        """Test sanitization with empty string."""
        result = sanitize_return_url("")
        assert result == "/"

    def test_sanitize_return_url_relative_valid(self):
        """Test sanitization with valid relative URLs."""
        assert sanitize_return_url("/dashboard") == "/dashboard"
        assert sanitize_return_url("/users/profile") == "/users/profile"
        assert sanitize_return_url("/api/v1/data") == "/api/v1/data"

    def test_sanitize_return_url_relative_invalid(self):
        """Test sanitization with invalid relative URLs."""
        # Double slash (protocol-relative)
        assert sanitize_return_url("//evil.com") == "/"

        # Control characters
        assert sanitize_return_url("/path\x00with\x01control") == "/"

    def test_sanitize_return_url_absolute_no_allowlist(self):
        """Test sanitization with absolute URLs and no allowlist."""
        assert sanitize_return_url("https://evil.com") == "/"
        assert sanitize_return_url("http://malicious.site") == "/"

    def test_sanitize_return_url_absolute_with_allowlist(self):
        """Test sanitization with absolute URLs and allowlist."""
        allowed_hosts = ["mysite.com", "api.mysite.com"]

        # Allowed hosts should pass
        assert (
            sanitize_return_url("https://mysite.com/dashboard", allowed_hosts)
            == "https://mysite.com/dashboard"
        )
        assert (
            sanitize_return_url("http://api.mysite.com/data", allowed_hosts)
            == "http://api.mysite.com/data"
        )

        # Non-allowed hosts should be rejected
        assert sanitize_return_url("https://evil.com/steal", allowed_hosts) == "/"

    def test_sanitize_return_url_malformed_absolute(self):
        """Test sanitization with malformed absolute URLs."""
        allowed_hosts = ["mysite.com"]

        # Malformed URLs should be rejected
        assert sanitize_return_url("https://", allowed_hosts) == "/"
        assert sanitize_return_url("not-a-url", allowed_hosts) == "/"


class TestClientFingerprinting:
    """Test client fingerprinting for session binding."""

    def test_hash_client_fingerprint_user_agent_only(self):
        """Test fingerprinting with user agent only."""
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

        fingerprint = hash_client_fingerprint(user_agent)

        assert isinstance(fingerprint, str)
        assert len(fingerprint) == 64  # SHA256 hex = 64 chars

        # Should be deterministic
        fingerprint2 = hash_client_fingerprint(user_agent)
        assert fingerprint == fingerprint2

    def test_hash_client_fingerprint_with_ip(self):
        """Test fingerprinting with user agent and IP."""
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        client_ip = "192.168.1.100"

        fingerprint = hash_client_fingerprint(user_agent, client_ip)

        assert isinstance(fingerprint, str)
        assert len(fingerprint) == 64

        # Should be different from user agent only
        fingerprint_ua_only = hash_client_fingerprint(user_agent)
        assert fingerprint != fingerprint_ua_only

    def test_hash_client_fingerprint_none_inputs(self):
        """Test fingerprinting with None inputs."""
        fingerprint = hash_client_fingerprint(None, None)

        assert isinstance(fingerprint, str)
        assert len(fingerprint) == 64

        # Should use fallback
        assert fingerprint is not None

    def test_validate_client_fingerprint_exact_match(self):
        """Test fingerprint validation with exact match."""
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        client_ip = "192.168.1.100"

        stored_fingerprint = hash_client_fingerprint(user_agent, client_ip)

        # Exact match should validate
        assert (
            validate_client_fingerprint(stored_fingerprint, user_agent, client_ip)
            is True
        )

        # Different user agent should fail
        assert (
            validate_client_fingerprint(stored_fingerprint, "Different UA", client_ip)
            is False
        )

        # Different IP should fail
        assert (
            validate_client_fingerprint(stored_fingerprint, user_agent, "192.168.1.200")
            is False
        )

    def test_validate_client_fingerprint_strict_mode(self):
        """Test fingerprint validation in strict mode."""
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        stored_fingerprint = hash_client_fingerprint(user_agent)

        # Exact match should pass
        assert (
            validate_client_fingerprint(stored_fingerprint, user_agent, strict=True)
            is True
        )

        # Any difference should fail in strict mode
        assert (
            validate_client_fingerprint(
                stored_fingerprint, user_agent + " modified", strict=True
            )
            is False
        )

    def test_validate_client_fingerprint_non_strict_mode(self):
        """Test fingerprint validation in non-strict mode."""
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        stored_fingerprint = hash_client_fingerprint(user_agent)

        # For now, non-strict still requires exact match
        # This could be enhanced with fuzzy matching in the future
        assert (
            validate_client_fingerprint(stored_fingerprint, user_agent, strict=False)
            is True
        )
        assert (
            validate_client_fingerprint(
                stored_fingerprint, user_agent + " modified", strict=False
            )
            is False
        )


class TestSecurityUtilsIntegration:
    """Integration tests for security utilities."""

    def test_full_csrf_flow(self):
        """Test complete CSRF token generation and validation flow."""
        with patch("src.app.runtime.context.get_config") as mock_config:
            mock_config.return_value.app.session_signing_secret = "test-secret-key"

            session_id = "user-session-abc123"

            # Generate token
            csrf_token = generate_csrf_token(session_id)

            # Should validate immediately
            assert validate_csrf_token(session_id, csrf_token) is True

            # Should not validate for different session
            assert validate_csrf_token("different-session", csrf_token) is False

            # Should not validate None
            assert validate_csrf_token(session_id, None) is False

    def test_full_fingerprint_flow(self):
        """Test complete client fingerprinting flow."""
        # Simulate initial request
        user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        client_ip = "10.0.0.5"

        # Generate fingerprint
        fingerprint = hash_client_fingerprint(user_agent, client_ip)

        # Simulate callback with same context
        assert validate_client_fingerprint(fingerprint, user_agent, client_ip) is True

        # Simulate callback with different context (potential attack)
        assert (
            validate_client_fingerprint(fingerprint, "Attacker Browser", client_ip)
            is False
        )
        assert (
            validate_client_fingerprint(fingerprint, user_agent, "192.168.1.200")
            is False
        )

    def test_url_sanitization_edge_cases(self):
        """Test edge cases in URL sanitization."""
        # Whitespace handling
        assert sanitize_return_url("  /dashboard  ") == "/dashboard"

        # Unicode handling
        assert sanitize_return_url("/üser/prøfile") == "/üser/prøfile"

        # Query parameters and fragments
        assert sanitize_return_url("/search?q=test#results") == "/search?q=test#results"

        # URL encoding
        assert sanitize_return_url("/path%20with%20spaces") == "/path%20with%20spaces"
