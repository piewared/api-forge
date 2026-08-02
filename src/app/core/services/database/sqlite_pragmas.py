"""SQLite connection pragmas.

SQLite ships with foreign-key enforcement *disabled*. A schema's ``FOREIGN KEY``
constraints are therefore inert unless ``PRAGMA foreign_keys=ON`` is issued on
every connection. PostgreSQL enforces them unconditionally, so an engine that
skips this pragma silently accepts referential-integrity violations locally and
only fails once the same code reaches Postgres.

This module owns that single concern: making a SQLite engine behave like the
production database with respect to referential integrity.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

_ENABLE_FOREIGN_KEYS = "PRAGMA foreign_keys=ON"


def enforce_sqlite_foreign_keys(engine: Engine) -> Engine:
    """Enable foreign-key enforcement on every connection this engine opens.

    Registers a ``connect`` listener rather than passing a connect argument
    because the pragma is per-connection: pooled and reconnected DBAPI handles
    must each receive it.

    Non-SQLite engines are returned untouched — they enforce constraints
    natively. The engine is returned so callers can wrap ``create_engine``
    directly.
    """
    if engine.dialect.name != "sqlite":
        return engine

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(_ENABLE_FOREIGN_KEYS)
        finally:
            cursor.close()

    return engine
