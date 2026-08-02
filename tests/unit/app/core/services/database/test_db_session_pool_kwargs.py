"""Unit tests for dialect-aware engine and connection arguments.

SQLite chooses its pool implementation from the database it points at, and the
in-memory pool rejects the server-oriented sizing arguments outright. Both
``_get_pool_kwargs`` and ``_get_connect_args`` therefore dispatch on the
database backend.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlmodel import create_engine

from src.app.core.services.database.db_session import DbSessionService
from src.app.runtime.config.config_data import AppConfig, ConfigData, DatabaseConfig

_POOL_KEYS = {"pool_size", "max_overflow", "pool_timeout", "pool_recycle"}


def _service() -> DbSessionService:
    # __init__ builds an engine from global config; the methods under test are
    # pure, so call them on an uninitialized instance.
    return DbSessionService.__new__(DbSessionService)


def _pool_kwargs(url: str) -> dict[str, object]:
    return _service()._get_pool_kwargs(DatabaseConfig(url=url))


def _connect_args(url: str, environment: str = "development") -> dict[str, object]:
    config = ConfigData(
        database=DatabaseConfig(url=url), app=AppConfig(environment=environment)
    )
    return _service()._get_connect_args(config)


class TestPoolKwargs:
    @pytest.mark.parametrize(
        "url",
        [
            "sqlite:///./database.db",
            "sqlite:///:memory:",
            "sqlite+aiosqlite:///./database.db",
        ],
    )
    def test_sqlite_gets_no_pool_sizing(self, url: str) -> None:
        assert _pool_kwargs(url) == {}

    def test_postgres_keeps_pool_sizing(self) -> None:
        kwargs = _pool_kwargs("postgresql://appuser@postgres:5432/appdb")

        assert _POOL_KEYS <= set(kwargs)
        assert kwargs["pool_size"] == DatabaseConfig().pool_size


class TestConnectArgs:
    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://appuser@postgres:5432/appdb",
            "postgresql+psycopg2://appuser@postgres:5432/appdb",
        ],
    )
    def test_postgres_gets_server_settings(self, url: str) -> None:
        """Driver-qualified URLs must still take the PostgreSQL branch."""
        args = _connect_args(url)

        assert args["application_name"] == "development_api"
        assert args["connect_timeout"] == 30
        assert args["options"] == "-c jit=off"

    @pytest.mark.parametrize(
        "url", ["sqlite:///./database.db", "sqlite+aiosqlite:///./database.db"]
    )
    def test_sqlite_gets_thread_and_lock_settings(self, url: str) -> None:
        args = _connect_args(url)

        assert args["check_same_thread"] is False
        assert args["timeout"] == 20
        assert "application_name" not in args

    def test_sqlite_branch_is_not_selected_by_a_postgres_password(self) -> None:
        """A credential containing "sqlite" must not reach the SQLite branch.

        The substring test this replaced happened to get this right, but only
        because it checked "postgresql" first — the correctness was incidental
        to branch ordering rather than to the test itself.
        """
        args = _connect_args("postgresql://appuser:sqlite-pw@postgres:5432/appdb")

        assert args["options"] == "-c jit=off"
        assert "check_same_thread" not in args

    def test_postgres_branch_is_not_selected_by_a_sqlite_path(self) -> None:
        """The real misroute: a SQLite file path containing "postgresql".

        The replaced substring test matched "postgresql" anywhere in the URL,
        so this SQLite database took the PostgreSQL branch and received
        server-only connect args (application_name, connect_timeout, options)
        that SQLite's DBAPI does not accept.
        """
        args = _connect_args("sqlite:///./postgresql_backup.db")

        assert args["check_same_thread"] is False
        assert "application_name" not in args

    def test_production_sqlite_still_returns_connect_args(self) -> None:
        """The production warning must not short-circuit the args."""
        args = _connect_args("sqlite:///./database.db", environment="production")

        assert args["check_same_thread"] is False
        assert args["timeout"] == 20


class TestEngineConstruction:
    """The regression: create_engine raised before the engine existed."""

    @pytest.mark.parametrize(
        "url", ["sqlite:///:memory:", "sqlite:///{tmp}/database.db"]
    )
    def test_sqlite_engine_builds_and_connects(self, url: str, tmp_path) -> None:
        resolved = url.format(tmp=tmp_path)
        engine = create_engine(
            DatabaseConfig(url=resolved).connection_string,
            connect_args={"check_same_thread": False, "timeout": 20},
            pool_pre_ping=True,
            **_pool_kwargs(resolved),
        )

        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1
