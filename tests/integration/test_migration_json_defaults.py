"""Alembic autogenerate on a JSON column with a server default, against
the dev Postgres.

Postgres has no ``json = json`` operator, so Alembic's default
server-default comparison crashes. ``migrations/env.py`` passes
``compare_server_default`` from ``migration_compare`` to avoid that.
These tests run the real comparison on a throwaway database.

Skips when the dev Postgres isn't reachable (``api-forge-cli dev up``).
Override the admin connection with ``TEST_POSTGRES_ADMIN_URL``.
"""

import os
import uuid
from collections.abc import Generator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import JSON, Column, MetaData, String, Table, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, ProgrammingError

from src.app.core.services.database.migration_compare import compare_server_default

# Dev-stack superuser (docker-compose.dev.yml) on the host-mapped port.
# Dev-only credentials; never a deployed database.
DEFAULT_ADMIN_URL = "postgresql://postgres:devpass@localhost:5433/postgres"


def _table(metadata: MetaData, default: str) -> Table:
    return Table(
        "json_default_probe",
        metadata,
        Column("id", String, primary_key=True),
        Column("tags", JSON, nullable=False, server_default=text(default)),
    )


@pytest.fixture
def probe_engine() -> Generator[Engine]:
    """A throwaway database holding one table with a JSON ``'[]'``
    server default."""
    admin = create_engine(
        os.environ.get("TEST_POSTGRES_ADMIN_URL", DEFAULT_ADMIN_URL),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect():
            pass
    except OperationalError as exc:
        admin.dispose()
        pytest.skip(f"dev Postgres not reachable: {exc.orig}")

    name = f"af_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(
        admin.url.set(database=name).render_as_string(hide_password=False)
    )
    try:
        _table(MetaData(), "'[]'").create(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _diffs(engine: Engine, metadata: MetaData, comparator: object) -> list:
    with engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"compare_type": True, "compare_server_default": comparator}
        )
        return list(compare_metadata(context, metadata))


def test_alembic_default_comparison_crashes_on_json(probe_engine: Engine) -> None:
    """Guards the premise: without the hook, autogenerate fails."""
    metadata = MetaData()
    _table(metadata, "'[]'")
    with pytest.raises(ProgrammingError, match="operator does not exist: json"):
        _diffs(probe_engine, metadata, True)


def test_matching_json_default_is_no_change(probe_engine: Engine) -> None:
    metadata = MetaData()
    _table(metadata, "'[]'")
    assert _diffs(probe_engine, metadata, compare_server_default) == []


def test_changed_json_default_is_detected(probe_engine: Engine) -> None:
    metadata = MetaData()
    _table(metadata, "'{}'")
    diffs = _diffs(probe_engine, metadata, compare_server_default)
    assert [d[0][0] for d in diffs] == ["modify_default"]
