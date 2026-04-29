"""Unit tests for LocalPostgresConnection."""

from unittest.mock import MagicMock

from src.infra.postgres.connection import DbSettings
from src.infra.postgres.local_connection import LocalPostgresConnection


def _make_settings(**overrides) -> MagicMock:
    """Build a mock DbSettings with sensible defaults."""
    settings = MagicMock(spec=DbSettings)
    settings.superuser = "postgres"
    settings.superuser_password = "super-secret"
    settings.user = "app_user"
    settings.password = "app-pass"
    settings.app_db = "myapp"
    for attr, val in overrides.items():
        setattr(settings, attr, val)
    return settings


class TestLocalPostgresConnection:
    """Tests for LocalPostgresConnection.get_dsn."""

    def test_get_dsn_returns_localhost(self) -> None:
        """Host must always be localhost regardless of settings."""
        conn = LocalPostgresConnection(_make_settings(), local_port=15432)
        dsn = conn.get_dsn()
        assert dsn["host"] == "localhost"

    def test_get_dsn_uses_configured_port(self) -> None:
        """The local_port passed at construction appears in the DSN."""
        conn = LocalPostgresConnection(_make_settings(), local_port=54321)
        dsn = conn.get_dsn()
        assert dsn["port"] == 54321

    def test_get_dsn_uses_app_user_by_default(self) -> None:
        """Normal mode uses the app user and password."""
        settings = _make_settings(user="appuser", password="apppass")
        conn = LocalPostgresConnection(settings, local_port=5432, superuser_mode=False)
        dsn = conn.get_dsn()
        assert dsn["user"] == "appuser"
        assert dsn["password"] == "apppass"

    def test_get_dsn_uses_superuser_when_requested(self) -> None:
        """Superuser mode uses the superuser credentials."""
        settings = _make_settings(
            superuser="postgres",
            superuser_password="rootpass",
        )
        conn = LocalPostgresConnection(settings, local_port=5432, superuser_mode=True)
        dsn = conn.get_dsn()
        assert dsn["user"] == "postgres"
        assert dsn["password"] == "rootpass"

    def test_get_dsn_uses_custom_database(self) -> None:
        """Passing a database name overrides the default."""
        conn = LocalPostgresConnection(_make_settings(app_db="myapp"), local_port=5432)
        dsn = conn.get_dsn("otherdb")
        assert dsn["dbname"] == "otherdb"

    def test_get_dsn_defaults_to_app_db(self) -> None:
        """Calling get_dsn() without args defaults to settings.app_db."""
        settings = _make_settings(app_db="myapp")
        conn = LocalPostgresConnection(settings, local_port=5432)
        dsn = conn.get_dsn()
        assert dsn["dbname"] == "myapp"

    def test_ssl_mode_reflected_in_dsn(self) -> None:
        """The ssl_mode constructor param appears in the returned DSN."""
        conn = LocalPostgresConnection(
            _make_settings(), local_port=5432, ssl_mode="require"
        )
        dsn = conn.get_dsn()
        assert dsn["sslmode"] == "require"
