"""Unit tests for SQLite foreign-key pragma enforcement."""

from __future__ import annotations

import pytest
from sqlalchemy import StaticPool, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import create_engine

from src.app.core.services.database.sqlite_pragmas import enforce_sqlite_foreign_keys


def _sqlite_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_returns_the_same_engine_for_chaining() -> None:
    engine = _sqlite_engine()

    assert enforce_sqlite_foreign_keys(engine) is engine


def test_pragma_is_off_without_enforcement() -> None:
    """Guards the premise: SQLite defaults to foreign keys disabled."""
    engine = _sqlite_engine()

    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 0


def test_pragma_is_enabled_on_connect() -> None:
    engine = enforce_sqlite_foreign_keys(_sqlite_engine())

    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_violating_insert_is_rejected() -> None:
    """The behavior that matters: a dangling FK fails like it would on Postgres."""
    engine = enforce_sqlite_foreign_keys(_sqlite_engine())

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE child ("
                "  id INTEGER PRIMARY KEY,"
                "  parent_id INTEGER REFERENCES parent(id)"
                ")"
            )
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO child (id, parent_id) VALUES (1, 999)"))


def test_violating_insert_is_accepted_without_enforcement() -> None:
    """Without the pragma the same insert silently succeeds — the bug this fixes."""
    engine = _sqlite_engine()

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE child ("
                "  id INTEGER PRIMARY KEY,"
                "  parent_id INTEGER REFERENCES parent(id)"
                ")"
            )
        )
        conn.execute(text("INSERT INTO child (id, parent_id) VALUES (1, 999)"))

    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM child")).scalar() == 1


def test_non_sqlite_engine_is_left_untouched() -> None:
    """A Postgres engine must not get a SQLite pragma listener attached."""
    engine = create_engine("postgresql://user:pass@localhost:5432/db")

    assert enforce_sqlite_foreign_keys(engine) is engine
