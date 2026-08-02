"""Unit tests for dialect dispatch in DatabaseConfig.connection_string.

``use_postgres`` defaults to no, so the default generated project runs on
SQLite. The connection string must therefore be usable for SQLite, not just
for PostgreSQL.
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from src.app.runtime.config.config_data import DatabaseConfig


class TestIsSqlite:
    @pytest.mark.parametrize(
        "url",
        [
            "sqlite:///./database.db",
            "sqlite:///:memory:",
            "sqlite+aiosqlite:///./database.db",
            "sqlite+pysqlite:///./database.db",
        ],
    )
    def test_detects_sqlite_including_driver_qualified_names(self, url: str) -> None:
        assert DatabaseConfig(url=url).is_sqlite is True

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://user@host:5432/db",
            "postgresql+asyncpg://user@host:5432/db",
        ],
    )
    def test_postgres_is_not_sqlite(self, url: str) -> None:
        assert DatabaseConfig(url=url).is_sqlite is False


class TestSqliteConnectionString:
    @pytest.mark.parametrize(
        "url",
        [
            "sqlite:///./database.db",
            "sqlite:///:memory:",
            "sqlite+aiosqlite:///./database.db",
            "sqlite:///./database.db?cache=shared",
        ],
    )
    def test_sqlite_urls_pass_through_verbatim(self, url: str) -> None:
        """The configured URL is already valid — nothing should be rewritten."""
        assert DatabaseConfig(url=url).connection_string == url

    def test_does_not_apply_postgres_user_or_app_db(self) -> None:
        """The regression this guards.

        SQLite has no user and its "database" is a file path, so applying the
        PostgreSQL ``user``/``app_db`` reconciliation produced
        ``postgresql://user@None:None/app_db``.
        """
        config = DatabaseConfig(
            url="sqlite:///./database.db", user="appuser", app_db="appdb"
        )

        assert config.connection_string == "sqlite:///./database.db"
        assert "postgresql" not in config.connection_string
        assert "None" not in config.connection_string

    def test_result_is_a_parsable_engine_url(self) -> None:
        """create_engine previously raised ValueError on the rendered string."""
        config = DatabaseConfig(url="sqlite:///./database.db")

        assert make_url(config.connection_string).drivername == "sqlite"

    def test_production_mode_adds_no_search_path_option(self) -> None:
        """search_path is a PostgreSQL schema concept."""
        config = DatabaseConfig(
            url="sqlite:///./database.db", environment_mode="production"
        )

        assert "search_path" not in config.connection_string

    def test_sanitized_string_is_unchanged_for_sqlite(self) -> None:
        config = DatabaseConfig(url="sqlite:///./database.db")

        assert config.sanitized_connection_string == "sqlite:///./database.db"


class TestDriverPreservation:
    """The configured DBAPI driver is an explicit choice and must survive.

    Rewriting ``postgresql+psycopg2`` to a bare ``postgresql`` silently swaps
    in SQLAlchemy's default driver.
    """

    @pytest.mark.parametrize(
        "drivername",
        ["postgresql", "postgresql+psycopg2", "postgresql+asyncpg"],
    )
    def test_driver_survives_rendering(self, drivername: str) -> None:
        config = DatabaseConfig(
            url=f"{drivername}://appuser:s3cret@postgres:5432/appdb",
            user="appuser",
            app_db="appdb",
        )

        assert config.connection_string.startswith(f"{drivername}://")
        assert make_url(config.connection_string).drivername == drivername

    def test_driver_survives_credential_reconciliation(self) -> None:
        """The rewrite happens after user/app_db overrides are applied."""
        config = DatabaseConfig(
            url="postgresql+psycopg2://olduser:s3cret@postgres:5432/olddb",
            user="appuser",
            app_db="appdb",
        )

        assert config.connection_string == (
            "postgresql+psycopg2://appuser:s3cret@postgres:5432/appdb"
        )


class TestBackendName:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("postgresql://u@h:5432/d", "postgresql"),
            ("postgresql+psycopg2://u@h:5432/d", "postgresql"),
            ("postgresql+asyncpg://u@h:5432/d", "postgresql"),
            ("sqlite:///./database.db", "sqlite"),
            ("sqlite+aiosqlite:///./database.db", "sqlite"),
        ],
    )
    def test_strips_the_driver_qualifier(self, url: str, expected: str) -> None:
        assert DatabaseConfig(url=url).backend_name == expected


class TestPostgresConnectionStringUnchanged:
    """The PostgreSQL path must be untouched by the dialect dispatch."""

    def test_renders_host_port_and_database(self) -> None:
        config = DatabaseConfig(
            url="postgresql://appuser@postgres:5432/appdb",
            user="appuser",
            app_db="appdb",
        )

        assert config.connection_string == "postgresql://appuser@postgres:5432/appdb"

    def test_includes_resolved_password(self) -> None:
        config = DatabaseConfig(
            url="postgresql://appuser:s3cret@postgres:5432/appdb",
            user="appuser",
            app_db="appdb",
        )

        assert config.connection_string == (
            "postgresql://appuser:s3cret@postgres:5432/appdb"
        )

    @pytest.mark.parametrize(
        "drivername", ["postgresql", "postgresql+psycopg2", "postgresql+asyncpg"]
    )
    def test_production_mode_sets_search_path_for_any_driver(
        self, drivername: str
    ) -> None:
        """Regression: this was keyed off the raw drivername, so a
        driver-qualified URL silently lost search_path in production."""
        # Production mode requires a resolvable password.
        config = DatabaseConfig(
            url=f"{drivername}://appuser:s3cret@postgres:5432/appdb",
            user="appuser",
            app_db="appdb",
            environment_mode="production",
        )

        assert "options=-csearch_path%3Dapp" in config.connection_string
