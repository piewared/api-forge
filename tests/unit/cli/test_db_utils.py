import pytest
import typer

from src.cli.commands import db_utils


def test_parse_connection_string_basic():
    conn_str = "postgres://user:pass@db.example.com:5432/mydb?sslmode=require"
    parsed = db_utils.parse_connection_string(conn_str)

    assert parsed["username"] == "user"
    assert parsed["password"] == "pass"
    assert parsed["host"] == "db.example.com"
    assert parsed["port"] == "5432"
    assert parsed["database"] == "mydb"
    assert parsed["sslmode"] == "require"


def test_build_connection_string_includes_password_when_requested():
    conn = db_utils.build_connection_string(
        username="app",
        host="localhost",
        port="5432",
        database="appdb",
        sslmode="verify-full",
        include_password=True,
        password="secret",
    )

    assert conn == "postgres://app:secret@localhost:5432/appdb?sslmode=verify-full"


def test_validate_external_db_params_applies_overrides():
    conn_str = "postgres://user:pass@db.example.com:5432/mydb?sslmode=require"
    result = db_utils.validate_external_db_params(
        connection_string=conn_str,
        host="override.example.com",
        port=None,
        username="override_user",
        password="override_pass",
        database=None,
        sslmode="verify-full",
    )

    assert result == (
        "override.example.com",
        "5432",
        "override_user",
        "override_pass",
        "mydb",
        "verify-full",
    )


def test_validate_external_db_params_missing_required_fields_raises():
    with pytest.raises(typer.Exit):
        db_utils.validate_external_db_params(
            connection_string=None,
            host=None,
            port=None,
            username=None,
            password=None,
            database=None,
            sslmode=None,
        )
