"""Unit tests for the ``dev db`` command group and its URL resolution."""

from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from src.cli.commands.db import local_url
from src.cli.commands.dev_db import dev_db_app


class TestDevelopmentEnvironmentScope:
    """APP_ENVIRONMENT must be forced to development, then restored."""

    def test_restores_a_previous_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APP_ENVIRONMENT", "production")

        with local_url._development_environment():
            assert os.environ["APP_ENVIRONMENT"] == "development"

        assert os.environ["APP_ENVIRONMENT"] == "production"

    def test_removes_the_variable_when_it_was_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("APP_ENVIRONMENT", raising=False)

        with local_url._development_environment():
            assert os.environ["APP_ENVIRONMENT"] == "development"

        assert "APP_ENVIRONMENT" not in os.environ

    def test_restores_on_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APP_ENVIRONMENT", "test")

        with pytest.raises(RuntimeError):
            with local_url._development_environment():
                raise RuntimeError("boom")

        assert os.environ["APP_ENVIRONMENT"] == "test"


class TestGetDevDatabaseUrl:
    def test_passes_sqlite_urls_through_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """connection_string always renders postgresql://, so SQLite must bypass it."""

        class _Db:
            url = "sqlite:///./database.db"
            connection_string = "postgresql://wrong@wrong/wrong"

        class _Config:
            database = _Db()

        monkeypatch.setattr(local_url, "load_config", lambda **_: _Config())

        assert local_url.get_dev_database_url() == "sqlite:///./database.db"

    def test_uses_connection_string_for_postgres(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The resolved string carries the real password, unlike str(URL)."""

        class _Db:
            url = "postgresql://appuser@localhost:5433/appdb"
            connection_string = "postgresql://appuser:s3cret@localhost:5433/appdb"

        class _Config:
            database = _Db()

        monkeypatch.setattr(local_url, "load_config", lambda **_: _Config())

        assert local_url.get_dev_database_url() == (
            "postgresql://appuser:s3cret@localhost:5433/appdb"
        )

    def test_raises_when_config_is_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        class _Paths:
            config_yaml = tmp_path / "nope.yaml"

        monkeypatch.setattr(local_url, "DEFAULT_PATHS", _Paths())

        with pytest.raises(FileNotFoundError):
            local_url.get_dev_database_url()


class TestDevDbCommands:
    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_url_masks_the_password(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.cli.commands.dev_db.get_dev_database_url",
            lambda: "postgresql://appuser:s3cret@localhost:5433/appdb",
        )

        result = runner.invoke(dev_db_app, ["url"])

        assert result.exit_code == 0
        assert "s3cret" not in result.output
        assert "appuser" in result.output

    def test_migrate_forwards_the_dev_url_to_alembic(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        def _fake_run_migration(**kwargs: object) -> bool:
            captured.update(kwargs)
            return True

        monkeypatch.setattr(
            "src.cli.commands.dev_db.get_dev_database_url",
            lambda: "sqlite:///./database.db",
        )
        monkeypatch.setattr(
            "src.cli.commands.dev_db.run_migration", _fake_run_migration
        )

        result = runner.invoke(dev_db_app, ["migrate", "upgrade"])

        assert result.exit_code == 0
        assert captured["action"] == "upgrade"
        assert captured["database_url"] == "sqlite:///./database.db"

    def test_migrate_passes_the_revision_message(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(
            "src.cli.commands.dev_db.get_dev_database_url",
            lambda: "sqlite:///./database.db",
        )
        monkeypatch.setattr(
            "src.cli.commands.dev_db.run_migration",
            lambda **kwargs: (captured.update(kwargs), True)[1],
        )

        result = runner.invoke(dev_db_app, ["migrate", "revision", "-m", "add widget"])

        assert result.exit_code == 0
        assert captured["action"] == "revision"
        assert captured["message"] == "add widget"
        assert captured["autogenerate"] is True

    def test_migrate_exits_nonzero_on_failure(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.cli.commands.dev_db.get_dev_database_url",
            lambda: "sqlite:///./database.db",
        )
        monkeypatch.setattr("src.cli.commands.dev_db.run_migration", lambda **_: False)

        result = runner.invoke(dev_db_app, ["migrate", "upgrade"])

        assert result.exit_code == 1


class TestDevDbRegistration:
    def test_db_is_reachable_under_dev(self) -> None:
        """Guards the drift this fixes: prod/k8s/fly had db, dev did not."""
        from src.cli.commands.dev import app as dev_app

        group_names = {
            group.name or getattr(group.typer_instance, "info", None)
            for group in dev_app.registered_groups
        }

        assert "db" in group_names
