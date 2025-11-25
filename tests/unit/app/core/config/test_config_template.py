"""Unit tests for config_template module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest
import yaml
from pydantic_core import ValidationError

from src.app.runtime.config.config_loader import (
    load_config,
    substitute_env_vars,
)


class TestSubstituteEnvVars:
    """Test cases for substitute_env_vars function."""

    def test_substitute_simple_env_var(self):
        """Test substitution of a simple environment variable."""
        with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            result = substitute_env_vars("${TEST_VAR}")
            assert result == "test_value"

    def test_substitute_env_var_in_text(self):
        """Test substitution of environment variable within text."""
        with patch.dict(os.environ, {"HOST": "localhost", "PORT": "8080"}):
            text = "Server running at http://${HOST}:${PORT}/api"
            result = substitute_env_vars(text)
            assert result == "Server running at http://localhost:8080/api"

    def test_substitute_env_var_with_default(self):
        """Test substitution with default value when env var is not set."""
        with patch.dict(os.environ, {}, clear=True):
            result = substitute_env_vars("${MISSING_VAR:-default_value}")
            assert result == "default_value"

    def test_substitute_env_var_with_default_when_set(self):
        """Test substitution with default value when env var is set."""
        with patch.dict(os.environ, {"PRESENT_VAR": "actual_value"}):
            result = substitute_env_vars("${PRESENT_VAR:-default_value}")
            assert result == "actual_value"

    def test_substitute_env_var_with_empty_default(self):
        """Test substitution with empty default value."""
        with patch.dict(os.environ, {}, clear=True):
            result = substitute_env_vars("${MISSING_VAR:-}")
            assert result == ""

    def test_substitute_required_env_var_missing(self):
        """Test substitution fails when required env var is missing."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(
                ValueError, match="Required environment variable MISSING_VAR not set"
            ):
                substitute_env_vars("${MISSING_VAR}")

    def test_substitute_env_var_with_custom_error(self):
        """Test substitution with custom error message."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(
                ValueError,
                match="Required environment variable MISSING_VAR: This is required for auth",
            ):
                substitute_env_vars("${MISSING_VAR:?This is required for auth}")

    def test_substitute_env_var_with_custom_error_when_set(self):
        """Test substitution with custom error when env var is actually set."""
        with patch.dict(os.environ, {"PRESENT_VAR": "value"}):
            result = substitute_env_vars("${PRESENT_VAR:?This should not error}")
            assert result == "value"

    def test_substitute_multiple_env_vars(self):
        """Test substitution of multiple environment variables."""
        env_vars = {"APP_NAME": "MyApp", "VERSION": "1.0.0", "ENV": "production"}
        with patch.dict(os.environ, env_vars):
            text = "${APP_NAME} v${VERSION} running in ${ENV} mode"
            result = substitute_env_vars(text)
            assert result == "MyApp v1.0.0 running in production mode"

    def test_substitute_mixed_env_var_formats(self):
        """Test substitution of mixed environment variable formats."""
        with patch.dict(os.environ, {"PRESENT": "value1"}, clear=True):
            text = "Present: ${PRESENT}, Default: ${MISSING:-default}, Required missing will error"
            result = substitute_env_vars(text)
            assert (
                result
                == "Present: value1, Default: default, Required missing will error"
            )

    def test_substitute_no_env_vars(self):
        """Test text with no environment variables remains unchanged."""
        text = "This is just plain text with no variables"
        result = substitute_env_vars(text)
        assert result == text

    def test_substitute_malformed_env_var(self):
        """Test text with malformed variable syntax remains unchanged."""
        text = "This has $MALFORMED and ${UNCLOSED variables"
        result = substitute_env_vars(text)
        assert result == text

    def test_substitute_env_var_empty_string(self):
        """Test substitution when environment variable is empty string."""
        with patch.dict(os.environ, {"EMPTY_VAR": ""}):
            result = substitute_env_vars("${EMPTY_VAR}")
            assert result == ""

    def test_substitute_complex_default_value(self):
        """Test substitution with complex default values."""
        with patch.dict(os.environ, {}, clear=True):
            result = substitute_env_vars(
                "${DB_URL:-postgresql://user:pass@localhost:5432/db}"
            )
            assert result == "postgresql://user:pass@localhost:5432/db"

    def test_substitute_nested_braces_in_default(self):
        """Test substitution with nested braces in default value."""
        with patch.dict(os.environ, {}, clear=True):
            # This should work as long as the outer braces are properly matched
            result = substitute_env_vars('${CONFIG:-{"key": "value"}}')
            assert result == '{"key": "value"}'


class TestLoadTemplatedYaml:
    """Test cases for load_templated_yaml function."""

    @pytest.fixture
    def sample_yaml_content(self):
        """Sample YAML content for testing."""
        return """
config:
  app:
    environment: ${APP_ENVIRONMENT:-development}
    host: ${HOST:-localhost}
    port: ${PORT:-8000}
  database:
    url: ${DATABASE_URL:-sqlite:///./database.db}
    pool_size: ${DB_POOL_SIZE:-5}
  redis:
    url: ${REDIS_URL:-redis://localhost:6379}
  oidc:
    providers:
      keycloak:
        client_id: ${OIDC_KEYCLOAK_CLIENT_ID}
        client_secret: ${OIDC_KEYCLOAK_CLIENT_SECRET}
        issuer: ${KEYCLOAK_ISSUER:-http://localhost:8080/realms/test-realm}
        authorization_endpoint: ${KEYCLOAK_AUTH_ENDPOINT:-http://localhost:8080/realms/test-realm/protocol/openid-connect/auth}
        token_endpoint: ${KEYCLOAK_TOKEN_ENDPOINT:-http://localhost:8080/realms/test-realm/protocol/openid-connect/token}
        jwks_uri: ${KEYCLOAK_JWKS_URI:-http://localhost:8080/realms/test-realm/protocol/openid-connect/certs}
        redirect_uri: ${KEYCLOAK_REDIRECT_URI:-http://localhost:8000/auth/callback}
"""

    def test_load_templated_yaml_success(self, sample_yaml_content):
        """Test successful loading and templating of YAML file."""
        env_vars = {
            "APP_ENVIRONMENT": "test",
            "HOST": "0.0.0.0",
            "PORT": "9000",
            "OIDC_KEYCLOAK_CLIENT_ID": "test-client",
            "OIDC_KEYCLOAK_CLIENT_SECRET": "test-secret",
        }

        with patch.dict(os.environ, env_vars):
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False
            ) as f:
                f.write(sample_yaml_content)
                f.flush()

                try:
                    config = load_config(Path(f.name))

                    assert config.app.environment == "test"
                    assert config.app.host == "0.0.0.0"
                    assert config.app.port == 9000
                    assert (
                        config.database.url
                        == "postgresql://appuser:devpass@localhost:5433/appdb"
                    )  # default value used
                    assert config.oidc.providers["keycloak"].client_id == "test-client"
                    assert (
                        config.oidc.providers["keycloak"].client_secret == "test-secret"
                    )
                finally:
                    os.unlink(f.name)

    def test_load_templated_yaml_missing_required_env_var(self, sample_yaml_content):
        """Test loading fails when required environment variable is missing."""
        with patch.dict(os.environ, {}, clear=True):
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False
            ) as f:
                f.write(sample_yaml_content)
                f.flush()

                try:
                    with pytest.raises(
                        ValueError,
                        match="Required environment variable OIDC_KEYCLOAK_CLIENT_ID not set",
                    ):
                        load_config(Path(f.name))
                finally:
                    os.unlink(f.name)

    def test_load_templated_yaml_file_not_found(self):
        """Test loading fails when YAML file doesn't exist."""
        non_existent_path = Path("/path/that/does/not/exist.yaml")
        with pytest.raises(FileNotFoundError):
            load_config(non_existent_path)

    def test_load_templated_yaml_invalid_yaml(self):
        """Test loading fails with invalid YAML syntax."""
        invalid_yaml = """
config:
  app:
    name: test
    invalid: [unclosed bracket
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(invalid_yaml)
            f.flush()

            try:
                with pytest.raises(ValueError, match="Error parsing YAML"):
                    load_config(Path(f.name))
            finally:
                os.unlink(f.name)

    def test_load_templated_yaml_empty_file(self):
        """Test loading fails with empty YAML file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()

            try:
                with pytest.raises(ValueError, match="Failed to parse YAML"):
                    load_config(Path(f.name))
            finally:
                os.unlink(f.name)

    def test_load_templated_yaml_missing_config_section(self):
        """Test loading with YAML that doesn't have config section."""
        yaml_without_config = """
some_other_section:
  key: value
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_without_config)
            f.flush()

            try:
                # Should create ConfigData with defaults when config section is missing
                config = load_config(Path(f.name))
                assert hasattr(config, "app")
                assert hasattr(config, "database")
            finally:
                os.unlink(f.name)

    def test_load_templated_yaml_invalid_config_structure(self):
        """Test loading fails with invalid config structure."""
        invalid_config = """
config:
  app:
    port: "not_a_number"  # This should be an integer
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(invalid_config)
            f.flush()

            try:
                with pytest.raises(ValueError, match="Invalid configuration"):
                    load_config(Path(f.name))
            finally:
                os.unlink(f.name)


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_end_to_end_config_loading(self):
        """Test complete config loading workflow."""
        yaml_content = """
config:
  app:
    environment: ${APP_ENVIRONMENT}
    host: ${HOST:-0.0.0.0}
    port: ${PORT:-8000}
  database:
    url: ${DATABASE_URL:-sqlite:///./database.db}
  redis:
    url: ${REDIS_URL:-redis://localhost:6379}
  oidc:
    providers:
      keycloak:
        client_id: ${OIDC_KEYCLOAK_CLIENT_ID}
        client_secret: ${OIDC_KEYCLOAK_CLIENT_SECRET}
        issuer: ${KEYCLOAK_ISSUER:-http://localhost:8080/realms/test-realm}
        authorization_endpoint: ${KEYCLOAK_AUTH_ENDPOINT:-http://localhost:8080/realms/test-realm/protocol/openid-connect/auth}
        token_endpoint: ${KEYCLOAK_TOKEN_ENDPOINT:-http://localhost:8080/realms/test-realm/protocol/openid-connect/token}
        jwks_uri: ${KEYCLOAK_JWKS_URI:-http://localhost:8080/realms/test-realm/protocol/openid-connect/certs}
        redirect_uri: ${KEYCLOAK_REDIRECT_URI:-http://localhost:8000/auth/callback}
"""
        env_vars = {
            "APP_ENVIRONMENT": "test",
            "PORT": "9000",
            "OIDC_KEYCLOAK_CLIENT_ID": "integration-client",
            "OIDC_KEYCLOAK_CLIENT_SECRET": "integration-secret",
        }

        with patch.dict(os.environ, env_vars):
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False
            ) as f:
                f.write(yaml_content)
                f.flush()

                try:
                    # Test that config loads successfully
                    config = load_config(Path(f.name))

                    # Verify all values are correctly substituted
                    assert config.app.environment == "test"
                    assert config.app.host == "0.0.0.0"  # default value used
                    assert config.app.port == 9000  # env var used
                    assert (
                        config.database.url
                        == "postgresql://appuser:devpass@localhost:5433/appdb"
                    )  # default value used
                    assert (
                        config.oidc.providers["keycloak"].client_id
                        == "integration-client"
                    )
                    assert (
                        config.oidc.providers["keycloak"].client_secret
                        == "integration-secret"
                    )
                    assert (
                        config.oidc.providers["keycloak"].issuer
                        == "http://localhost:8080/realms/test-realm"
                    )  # default
                finally:
                    os.unlink(f.name)

    def test_error_propagation_chain(self):
        """Test that errors propagate correctly through the function chain."""
        yaml_content = """
config:
  app:
    environment: ${REQUIRED_VAR:?This variable is absolutely required}
"""

        with patch.dict(os.environ, {}, clear=True):
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yaml", delete=False
            ) as f:
                f.write(yaml_content)
                f.flush()

                try:
                    # Should fail during env var substitution
                    with pytest.raises(
                        ValueError, match="This variable is absolutely required"
                    ):
                        load_config(Path(f.name))
                finally:
                    os.unlink(f.name)


# Fixtures for common test data
@pytest.fixture
def temp_yaml_file():
    """Create a temporary YAML file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yield f
        os.unlink(f.name)


@pytest.fixture
def clean_env():
    """Provide a clean environment for testing."""
    original_env = dict(os.environ)
    os.environ.clear()
    yield
    os.environ.clear()
    os.environ.update(original_env)
