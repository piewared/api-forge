"""Server-default comparison for Alembic autogenerate.

Alembic compares a model's ``server_default`` with the live database by
running ``SELECT <db default> = <model default>``. PostgreSQL's ``json``
type has no equality operator, so that query fails and autogenerate
crashes on any JSON column that declares a default (e.g. a list
column with ``server_default=text("'[]'")``). This module owns that
single concern: compare JSON defaults textually, and defer to Alembic
for every other column.

Wired into ``migrations/env.py``; any other ``compare_metadata`` caller
should pass the same hook.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import JSON

# Postgres reflects a JSON default as e.g. ``'[]'::json`` or ``'{}'::jsonb``.
_JSON_CAST = re.compile(r"::jsonb?$")


def _normalize(default: str) -> str:
    return _JSON_CAST.sub("", default.strip())


def compare_server_default(
    context: Any,
    inspected_column: Any,
    metadata_column: Any,
    inspected_default: str | None,
    metadata_default: Any,
    rendered_metadata_default: str | None,
) -> bool | None:
    """Alembic ``compare_server_default`` hook.

    Returns ``True`` when a JSON column's defaults differ, ``False`` when
    they match, and ``None`` (Alembic's own comparison) for everything
    else, including JSON columns where either side has no default.
    """
    if not isinstance(metadata_column.type, JSON):
        return None
    if inspected_default is None or rendered_metadata_default is None:
        return None
    return _normalize(inspected_default) != _normalize(rendered_metadata_default)
