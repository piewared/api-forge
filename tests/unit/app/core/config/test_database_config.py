"""Unit tests for DatabaseConfig password resolution logic."""

import os
import tempfile
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.app.runtime.config.config_data import DatabaseConfig


class TestDatabaseConfigPasswordResolution:
    """Test cases for the DatabaseConfig.password computed field."""

    def test_development_mode_password_from_url(self):
        """Test password extraction from URL in development mode."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user:mypassword@localhost:5432/testdb",
            environment_mode="development",
        )

        assert config.password == "mypassword"

    def test_development_mode_password_from_url_with_special_chars(self):
        """Test password extraction from URL with special characters."""
        # URL-encoded password with special characters
        config = DatabaseConfig(
            url="postgresql+asyncpg://user:my%40pass%21word@localhost:5432/testdb",
            environment_mode="development",
        )

        # SQLAlchemy should decode this automatically
        assert config.password == "my@pass!word"

    def test_development_mode_no_password_in_url_returns_none(self):
        """Test that missing password in URL returns None in development mode."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user@localhost:5432/testdb",
            environment_mode="development",
        )

        assert config.password is None

    def test_test_mode_password_from_url(self):
        """Test password extraction from URL in test mode (same as development)."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://testuser:testpass@localhost:5432/testdb",
            environment_mode="test",
        )

        assert config.password == "testpass"

    def test_test_mode_no_password_in_url_returns_none(self):
        """Test that missing password in URL returns None in test mode."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://testuser@localhost:5432/testdb",
            environment_mode="test",
        )

        assert config.password is None

    def test_production_mode_password_from_file(self):
        """Test password reading from file in production mode."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
            temp_file.write("production_secret_password")
            temp_file_path = temp_file.name

        try:
            config = DatabaseConfig(
                url="postgresql+asyncpg://user@postgres:5432/appdb",
                environment_mode="production",
                password_file_path=temp_file_path,
            )

            assert config.password == "production_secret_password"
        finally:
            os.unlink(temp_file_path)

    def test_production_mode_password_from_file_with_whitespace(self):
        """Test password reading from file strips whitespace."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
            temp_file.write("  production_password_with_spaces  \n")
            temp_file_path = temp_file.name

        try:
            config = DatabaseConfig(
                url="postgresql+asyncpg://user@postgres:5432/appdb",
                environment_mode="production",
                password_file_path=temp_file_path,
            )

            assert config.password == "production_password_with_spaces"
        finally:
            os.unlink(temp_file_path)

    def test_production_mode_password_file_not_found_raises_error(self):
        """Test that non-existent password file raises ValueError."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user@postgres:5432/appdb",
            environment_mode="production",
            password_file_path="/nonexistent/password/file",
        )

        with pytest.raises(FileNotFoundError):
            _ = config.password

    def test_production_mode_password_file_permission_error(self):
        """Test handling of file permission errors."""
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"secret")
            temp_file_path = temp_file.name

        try:
            # Remove read permissions
            os.chmod(temp_file_path, 0o000)

            config = DatabaseConfig(
                url="postgresql+asyncpg://user@postgres:5432/appdb",
                environment_mode="production",
                password_file_path=temp_file_path,
            )

            with pytest.raises(PermissionError):
                _ = config.password
        finally:
            # Restore permissions for cleanup
            os.chmod(temp_file_path, 0o644)
            os.unlink(temp_file_path)

    @patch.dict(os.environ, {"DB_PASSWORD": "env_secret_password"})
    def test_production_mode_password_from_environment_variable(self):
        """Test password reading from environment variable in production mode."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user@postgres:5432/appdb",
            environment_mode="production",
            password_env_var="DB_PASSWORD",
        )

        assert config.password == "env_secret_password"

    @patch.dict(os.environ, {}, clear=True)
    def test_production_mode_environment_variable_not_set_raises_error(self):
        """Test that missing environment variable raises ValueError."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user@postgres:5432/appdb",
            environment_mode="production",
            password_env_var="MISSING_DB_PASSWORD",
        )

        with pytest.raises(
            ValueError, match="Database password not provided in production mode"
        ):
            _ = config.password

    @patch.dict(os.environ, {"DB_PASSWORD": ""})
    def test_production_mode_empty_environment_variable_raises_error(self):
        """Test that empty environment variable raises ValueError."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user@postgres:5432/appdb",
            environment_mode="production",
            password_env_var="DB_PASSWORD",
        )

        with pytest.raises(
            ValueError, match="Database password not provided in production mode"
        ):
            _ = config.password

    def test_production_mode_env_var_takes_precedence_over_file(self):
        """Test that password_file_path takes precedence over environment variable."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
            temp_file.write("file_password")
            temp_file_path = temp_file.name

        try:
            with patch.dict(os.environ, {"DB_PASSWORD": "env_password"}):
                config = DatabaseConfig(
                    url="postgresql+asyncpg://user@postgres:5432/appdb",
                    environment_mode="production",
                    password_file_path=temp_file_path,
                    password_env_var="DB_PASSWORD",
                )

                assert config.password == "env_password"
        finally:
            os.unlink(temp_file_path)

    def test_production_mode_no_password_source_raises_error(self):
        """Test that production mode without password sources raises ValueError."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user@postgres:5432/appdb",
            environment_mode="production",
        )

        with pytest.raises(
            ValueError,
            match="Database password not provided in production mode",
        ):
            _ = config.password

    def test_invalid_environment_mode_raises_error(self):
        """Test that invalid environment mode raises ValueError."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user:password@localhost:5432/testdb",
            environment_mode="invalid_mode",
        )

        with pytest.raises(
            ValueError,
            match="Invalid environment_mode; must be 'development', 'production', or 'test'",
        ):
            _ = config.password

    def test_sqlite_url_in_development_mode(self):
        """Test password extraction from SQLite URL in development mode."""
        config = DatabaseConfig(
            url="sqlite:///./database.db", environment_mode="development"
        )

        # SQLite URLs don't have passwords, so this should return None
        assert config.password is None

    def test_complex_postgresql_url_parsing(self):
        """Test password extraction from complex PostgreSQL URLs."""
        # Test URL with query parameters
        config = DatabaseConfig(
            url="postgresql+asyncpg://user:complex%40pass@localhost:5432/db?sslmode=require&application_name=myapp",
            environment_mode="development",
        )

        assert config.password == "complex@pass"

    @patch.dict(os.environ, {"PROD_DB_PASS": "multi_line_password\nwith_newlines"})
    def test_production_mode_environment_variable_with_newlines(self):
        """Test handling of environment variables with newlines."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user@postgres:5432/appdb",
            environment_mode="production",
            password_env_var="PROD_DB_PASS",
        )

        # Environment variables preserve newlines
        assert config.password == "multi_line_password\nwith_newlines"

    def test_production_mode_password_from_file_with_newlines(self):
        """Test password reading from file with newlines gets stripped."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
            temp_file.write("password_with_newlines\n\n")
            temp_file_path = temp_file.name

        try:
            config = DatabaseConfig(
                url="postgresql+asyncpg://user@postgres:5432/appdb",
                environment_mode="production",
                password_file_path=temp_file_path,
            )

            # File reading strips whitespace including newlines
            assert config.password == "password_with_newlines"
        finally:
            os.unlink(temp_file_path)

    def test_password_property_is_computed_field(self):
        """Test that password is accessible as a computed field."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user:testpass@localhost:5432/testdb",
            environment_mode="development",
        )

        # Should be accessible as an attribute
        assert hasattr(config, "password")
        assert config.password == "testpass"

        # Should also be in the model dump when computed fields are included
        model_data = config.model_dump(include={"password"})
        assert "password" in model_data
        assert model_data["password"] == "testpass"

    def test_password_caching_behavior(self):
        """Test that password computation is consistent across multiple accesses."""
        config = DatabaseConfig(
            url="postgresql+asyncpg://user:testpass@localhost:5432/testdb",
            environment_mode="development",
        )

        # Multiple accesses should return the same result
        password1 = config.password
        password2 = config.password
        password3 = config.password

        assert password1 == password2 == password3 == "testpass"
