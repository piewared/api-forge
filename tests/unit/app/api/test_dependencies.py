"""Unit tests for dependency injection functions, focusing on origin validation."""

from unittest.mock import Mock

import pytest
from fastapi import HTTPException, Request

from src.app.api.http.deps import (
    enforce_origin,
    get_allowed_origins,
    is_origin_allowed,
    normalize_origin,
    require_csrf,
)
from src.app.core.security import generate_csrf_token
from src.app.runtime.config.config_data import AppConfig, ConfigData, CORSConfig
from src.app.runtime.context import with_context


class TestNormalizeOrigin:
    """Test the normalize_origin function."""

    def test_normalize_https_default_port(self):
        """Test normalizing HTTPS origin with default port."""
        result = normalize_origin("https://example.com")
        assert result == ("https", "example.com", 443)

    def test_normalize_http_default_port(self):
        """Test normalizing HTTP origin with default port."""
        result = normalize_origin("http://example.com")
        assert result == ("http", "example.com", 80)

    def test_normalize_https_custom_port(self):
        """Test normalizing HTTPS origin with custom port."""
        result = normalize_origin("https://example.com:8443")
        assert result == ("https", "example.com", 8443)

    def test_normalize_http_custom_port(self):
        """Test normalizing HTTP origin with custom port."""
        result = normalize_origin("http://example.com:8080")
        assert result == ("http", "example.com", 8080)

    def test_normalize_with_path_ignored(self):
        """Test that path is ignored during normalization."""
        result = normalize_origin("https://example.com/some/path")
        assert result == ("https", "example.com", 443)

    def test_normalize_with_query_ignored(self):
        """Test that query parameters are ignored during normalization."""
        result = normalize_origin("https://example.com?param=value")
        assert result == ("https", "example.com", 443)

    def test_normalize_case_insensitive_scheme(self):
        """Test that scheme is normalized to lowercase."""
        result = normalize_origin("HTTPS://EXAMPLE.COM")
        assert result == ("https", "example.com", 443)

    def test_normalize_case_insensitive_hostname(self):
        """Test that hostname is normalized to lowercase."""
        result = normalize_origin("https://EXAMPLE.COM")
        assert result == ("https", "example.com", 443)

    def test_normalize_localhost(self):
        """Test normalizing localhost origins."""
        result = normalize_origin("http://localhost:3000")
        assert result == ("http", "localhost", 3000)

    def test_normalize_ip_address(self):
        """Test normalizing IP address origins."""
        result = normalize_origin("http://192.168.1.1:8080")
        assert result == ("http", "192.168.1.1", 8080)

    def test_normalize_with_subdomain(self):
        """Test normalizing origins with subdomains."""
        result = normalize_origin("https://api.example.com")
        assert result == ("https", "api.example.com", 443)


class TestGetAllowedOrigins:
    """Test the get_allowed_origins function."""

    def test_get_allowed_origins_single(self):
        """Test getting allowed origins with single origin."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        with with_context(config_override=config):
            # Clear cache
            get_allowed_origins.cache_clear()
            result = get_allowed_origins()
            expected = {("https", "example.com", 443)}
            assert result == expected

    def test_get_allowed_origins_multiple(self):
        """Test getting allowed origins with multiple origins."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = [
            "https://example.com",
            "http://localhost:3000",
            "https://api.example.com:8443",
        ]

        with with_context(config_override=config):
            get_allowed_origins.cache_clear()
            result = get_allowed_origins()
            expected = {
                ("https", "example.com", 443),
                ("http", "localhost", 3000),
                ("https", "api.example.com", 8443),
            }
            assert result == expected

    def test_get_allowed_origins_empty(self):
        """Test getting allowed origins with empty list."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = []

        with with_context(config_override=config):
            get_allowed_origins.cache_clear()
            result = get_allowed_origins()
            assert result == set()

    def test_get_allowed_origins_wildcard(self):
        """Test getting allowed origins with wildcard."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["*"]

        with with_context(config_override=config):
            get_allowed_origins.cache_clear()
            result = get_allowed_origins()
            # Wildcard should be normalized as-is (this is a special case)
            # The actual wildcard handling should be done at a higher level
            assert len(result) == 1

    def test_get_allowed_origins_caching(self):
        """Test that get_allowed_origins uses caching."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        with with_context(config_override=config):
            get_allowed_origins.cache_clear()

            # First call
            result1 = get_allowed_origins()

            # Second call should return cached result
            result2 = get_allowed_origins()

            # Both results should be identical
            assert result1 is result2
            assert result1 == {("https", "example.com", 443)}


class TestIsOriginAllowed:
    """Test the is_origin_allowed function."""

    def test_is_origin_allowed_exact_match(self):
        """Test origin validation with exact match."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        with with_context(config_override=config):
            get_allowed_origins.cache_clear()
            assert is_origin_allowed("https://example.com") is True

    def test_is_origin_allowed_case_insensitive(self):
        """Test origin validation is case insensitive."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        with with_context(config_override=config):
            get_allowed_origins.cache_clear()
            assert is_origin_allowed("HTTPS://EXAMPLE.COM") is True
            assert is_origin_allowed("https://EXAMPLE.com") is True

    def test_is_origin_allowed_port_specific(self):
        """Test origin validation with specific ports."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com:8443"]

        with with_context(config_override=config):
            get_allowed_origins.cache_clear()
            assert is_origin_allowed("https://example.com:8443") is True
            assert is_origin_allowed("https://example.com") is False  # Default port 443
            assert is_origin_allowed("https://example.com:443") is False

    def test_is_origin_allowed_default_ports(self):
        """Test origin validation with default ports."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com", "http://example.com"]

        with with_context(config_override=config):
            get_allowed_origins.cache_clear()
            # HTTPS default port
            assert is_origin_allowed("https://example.com") is True
            assert is_origin_allowed("https://example.com:443") is True

            # HTTP default port
            assert is_origin_allowed("http://example.com") is True
            assert is_origin_allowed("http://example.com:80") is True

    def test_is_origin_allowed_subdomain_mismatch(self):
        """Test origin validation rejects subdomain mismatches."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        with with_context(config_override=config):
            get_allowed_origins.cache_clear()
            assert is_origin_allowed("https://api.example.com") is False
            assert is_origin_allowed("https://sub.example.com") is False

    def test_is_origin_allowed_scheme_mismatch(self):
        """Test origin validation rejects scheme mismatches."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        with with_context(config_override=config):
            get_allowed_origins.cache_clear()
            assert is_origin_allowed("http://example.com") is False

    def test_is_origin_allowed_not_in_list(self):
        """Test origin validation rejects origins not in allowed list."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        with with_context(config_override=config):
            get_allowed_origins.cache_clear()
            assert is_origin_allowed("https://evil.com") is False
            assert is_origin_allowed("https://different.com") is False

    def test_is_origin_allowed_empty_list(self):
        """Test origin validation with empty allowed list."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.cors = CORSConfig()
        config.app.cors.origins = []

        with with_context(config_override=config):
            get_allowed_origins.cache_clear()
            assert is_origin_allowed("https://example.com") is False


class TestEnforceOrigin:
    """Test the enforce_origin function."""

    def setup_method(self):
        """Clear caches before each test."""
        get_allowed_origins.cache_clear()

    def create_mock_request(self, method="POST", origin=None, referer=None, host=None):
        """Helper to create mock request objects."""
        request = Mock(spec=Request)
        request.method = method

        # Create a custom headers dict-like object
        headers_dict = {}
        if origin is not None:
            headers_dict["origin"] = origin
        if referer is not None:
            headers_dict["referer"] = referer
        if host is not None:
            headers_dict["host"] = host

        # Mock headers as an object with a get method
        request.headers = Mock()
        request.headers.get.side_effect = lambda key, default=None: headers_dict.get(
            key, default
        )

        return request

    def test_enforce_origin_allows_options(self):
        """Test that OPTIONS requests are always allowed."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = []

        request = self.create_mock_request(method="OPTIONS")

        with with_context(config_override=config):
            # Should not raise any exception
            enforce_origin(request)

    def test_enforce_origin_skips_get_requests(self):
        """Test that GET requests are not enforced."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = []

        request = self.create_mock_request(method="GET")

        with with_context(config_override=config):
            # Should not raise any exception
            enforce_origin(request)

    def test_enforce_origin_skips_development_mode(self):
        """Test that development mode skips origin enforcement."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "development"
        config.app.cors = CORSConfig()
        config.app.cors.origins = []

        request = self.create_mock_request(method="POST", origin="https://evil.com")

        with with_context(config_override=config):
            # Should not raise any exception
            enforce_origin(request)

    def test_enforce_origin_skips_test_mode(self):
        """Test that test mode skips origin enforcement."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "test"
        config.app.cors = CORSConfig()
        config.app.cors.origins = []

        request = self.create_mock_request(method="POST", origin="https://evil.com")

        with with_context(config_override=config):
            # Should not raise any exception
            enforce_origin(request)

    def test_enforce_origin_valid_origin_allowed(self):
        """Test that valid origins are allowed."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        request = self.create_mock_request(method="POST", origin="https://example.com")

        with with_context(config_override=config):
            # Should not raise any exception
            enforce_origin(request)

    def test_enforce_origin_invalid_origin_rejected(self):
        """Test that invalid origins are rejected."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        request = self.create_mock_request(method="POST", origin="https://evil.com")

        with with_context(config_override=config):
            with pytest.raises(HTTPException) as exc_info:
                enforce_origin(request)
            assert exc_info.value.status_code == 403
            assert "Origin not allowed" in str(exc_info.value.detail)

    def test_enforce_origin_null_origin_rejected(self):
        """Test that 'null' origin is rejected."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        request = self.create_mock_request(method="POST", origin="null")

        with with_context(config_override=config):
            with pytest.raises(HTTPException) as exc_info:
                enforce_origin(request)
            assert exc_info.value.status_code == 403
            assert "Origin 'null' not allowed" in str(exc_info.value.detail)

    def test_enforce_origin_fallback_to_referer(self):
        """Test fallback to referer when origin is missing."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        request = self.create_mock_request(
            method="POST", referer="https://example.com/some/page"
        )

        with with_context(config_override=config):
            # Should not raise any exception (referer matches allowed origin)
            enforce_origin(request)

    def test_enforce_origin_referer_fallback_rejected(self):
        """Test referer fallback is rejected for invalid origins."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        request = self.create_mock_request(
            method="POST", referer="https://evil.com/attack"
        )

        with with_context(config_override=config):
            with pytest.raises(HTTPException) as exc_info:
                enforce_origin(request)
            assert exc_info.value.status_code == 403
            assert "Referer origin not allowed" in str(exc_info.value.detail)

    def test_enforce_origin_host_header_fallback(self):
        """Test fallback to host header when origin and referer are missing."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        request = self.create_mock_request(method="POST", host="example.com")

        with with_context(config_override=config):
            # Should not raise any exception (host matches allowed origin)
            enforce_origin(request)

    def test_enforce_origin_missing_all_headers(self):
        """Test rejection when all origin-related headers are missing."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com"]

        request = self.create_mock_request(method="POST")

        with with_context(config_override=config):
            with pytest.raises(HTTPException) as exc_info:
                enforce_origin(request)
            assert exc_info.value.status_code == 403
            assert "Missing or invalid Origin" in str(exc_info.value.detail)

    def test_enforce_origin_post_method(self):
        """Test that POST methods are enforced."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = []

        request = self.create_mock_request(method="POST", origin="https://evil.com")

        with with_context(config_override=config):
            with pytest.raises(HTTPException):
                enforce_origin(request)

    def test_enforce_origin_put_method(self):
        """Test that PUT methods are enforced."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = []

        request = self.create_mock_request(method="PUT", origin="https://evil.com")

        with with_context(config_override=config):
            with pytest.raises(HTTPException):
                enforce_origin(request)

    def test_enforce_origin_patch_method(self):
        """Test that PATCH methods are enforced."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = []

        request = self.create_mock_request(method="PATCH", origin="https://evil.com")

        with with_context(config_override=config):
            with pytest.raises(HTTPException):
                enforce_origin(request)

    def test_enforce_origin_delete_method(self):
        """Test that DELETE methods are enforced."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = []

        request = self.create_mock_request(method="DELETE", origin="https://evil.com")

        with with_context(config_override=config):
            with pytest.raises(HTTPException):
                enforce_origin(request)

    def test_enforce_origin_with_port_matching(self):
        """Test origin enforcement with explicit port matching."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = ["https://example.com:8443"]

        # Valid port
        request_valid = self.create_mock_request(
            method="POST", origin="https://example.com:8443"
        )

        # Invalid port
        request_invalid = self.create_mock_request(
            method="POST", origin="https://example.com:9000"
        )

        with with_context(config_override=config):
            # Valid port should pass
            enforce_origin(request_valid)

            # Invalid port should fail
            with pytest.raises(HTTPException):
                enforce_origin(request_invalid)

    def test_enforce_origin_complex_scenario(self):
        """Test complex scenario with multiple allowed origins."""
        config = ConfigData()
        config.app = AppConfig()
        config.app.environment = "production"
        config.app.cors = CORSConfig()
        config.app.cors.origins = [
            "https://app.example.com",
            "https://admin.example.com:8443",
            "http://localhost:3000",
        ]

        test_cases = [
            # Valid cases
            ("POST", "https://app.example.com", True),
            ("POST", "https://admin.example.com:8443", True),
            ("POST", "http://localhost:3000", True),
            # Invalid cases
            ("POST", "https://evil.com", False),
            ("POST", "https://example.com", False),  # Missing subdomain
            ("POST", "https://admin.example.com", False),  # Missing port
            ("POST", "https://localhost:3000", False),  # Wrong scheme
        ]

        with with_context(config_override=config):
            for method, origin, should_pass in test_cases:
                request = self.create_mock_request(method=method, origin=origin)

                if should_pass:
                    # Should not raise exception
                    enforce_origin(request)
                else:
                    # Should raise exception
                    with pytest.raises(HTTPException):
                        enforce_origin(request)


# ---------- require_csrf ----------


def _make_csrf_request(
    method: str = "POST",
    csrf_header: str | None = None,
    user_session_id: str | None = None,
) -> Request:
    """Build a Starlette Request scope for require_csrf tests."""
    headers = []
    if csrf_header is not None:
        headers.append((b"x-csrf-token", csrf_header.encode("latin-1")))
    if user_session_id is not None:
        cookie_value = f"user_session_id={user_session_id}".encode("latin-1")
        headers.append((b"cookie", cookie_value))
    scope = {
        "type": "http",
        "method": method,
        "path": "/",
        "query_string": b"",
        "headers": headers,
    }
    return Request(scope)


def _production_config() -> ConfigData:
    """Production config with CSRF/session secrets so tokens can be generated."""
    config = ConfigData()
    config.app = AppConfig()
    config.app.environment = "production"
    config.app.csrf_signing_secret = "csrf-prod-secret-32-bytes-padded"
    config.app.session_signing_secret = "session-prod-secret-32-bytes-pad"
    return config


class TestRequireCSRF:
    """require_csrf has 5 branches; the dev/test early-exits are exercised
    elsewhere. These tests cover the production enforcement paths."""

    def test_options_preflight_is_allowed(self) -> None:
        """OPTIONS requests skip CSRF enforcement (CORS preflight)."""
        with with_context(config_override=_production_config()):
            require_csrf(_make_csrf_request(method="OPTIONS"))  # must not raise

    def test_get_requests_skip_enforcement(self) -> None:
        """Read-only verbs are not state-changing; CSRF is irrelevant."""
        with with_context(config_override=_production_config()):
            require_csrf(_make_csrf_request(method="GET"))

    def test_missing_csrf_header_is_rejected_in_production(self) -> None:
        with with_context(config_override=_production_config()):
            with pytest.raises(HTTPException) as exc_info:
                require_csrf(_make_csrf_request(method="POST", csrf_header=None))
        assert exc_info.value.status_code == 403
        assert "Missing CSRF token" in exc_info.value.detail

    def test_csrf_header_without_session_is_rejected(self) -> None:
        with with_context(config_override=_production_config()):
            with pytest.raises(HTTPException) as exc_info:
                require_csrf(
                    _make_csrf_request(
                        method="POST",
                        csrf_header="some-token",
                        user_session_id=None,
                    )
                )
        assert exc_info.value.status_code == 401
        assert "No session found" in exc_info.value.detail

    def test_invalid_csrf_token_is_rejected(self) -> None:
        with with_context(config_override=_production_config()):
            with pytest.raises(HTTPException) as exc_info:
                require_csrf(
                    _make_csrf_request(
                        method="POST",
                        csrf_header="not-a-valid-token",
                        user_session_id="session-id",
                    )
                )
        assert exc_info.value.status_code == 403
        assert "Invalid CSRF token" in exc_info.value.detail

    def test_valid_csrf_token_passes(self) -> None:
        """End-to-end: a token generated for the same session must validate."""
        config = _production_config()
        with with_context(config_override=config):
            valid_token = generate_csrf_token("session-id")
            require_csrf(
                _make_csrf_request(
                    method="POST",
                    csrf_header=valid_token,
                    user_session_id="session-id",
                )
            )  # must not raise
