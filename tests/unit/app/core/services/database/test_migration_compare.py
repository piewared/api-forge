"""JSON-aware server-default comparison for Alembic autogenerate."""

from sqlalchemy import JSON, Column, String
from sqlalchemy.dialects.postgresql import JSONB

from src.app.core.services.database.migration_compare import (
    compare_server_default,
)


def compare(column: Column, inspected: str | None, rendered: str | None) -> bool | None:
    return compare_server_default(None, None, column, inspected, None, rendered)


class TestJsonColumns:
    def test_reflected_cast_matches_model_literal(self) -> None:
        assert compare(Column("roles", JSON), "'[]'::json", "'[]'") is False

    def test_jsonb_cast_matches(self) -> None:
        assert compare(Column("meta", JSONB), "'{}'::jsonb", "'{}'") is False

    def test_different_defaults_reported(self) -> None:
        assert compare(Column("roles", JSON), "'[]'::json", "'{}'") is True

    def test_missing_side_defers_to_alembic(self) -> None:
        # Added or removed defaults are Alembic's normal job.
        assert compare(Column("roles", JSON), None, "'[]'") is None
        assert compare(Column("roles", JSON), "'[]'::json", None) is None


def test_non_json_columns_defer_to_alembic() -> None:
    assert compare(Column("name", String), "'x'::character varying", "'x'") is None
