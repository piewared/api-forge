"""``load_project_env`` precedence tests.

The canonical order is shell > .env.dev (development only) > .env.
Regressions here are how the dev worker and ``dev db migrate`` ended
up crash-looping on required config vars whose values only exist as
dev placeholders in ``.env.dev``.

Also pins the docker-compose mirror of the same precedence: compose
``env_file`` gives the LATER file precedence, so the dev worker must
list ``.env`` before ``.env.dev``.
"""

import os
from pathlib import Path

import pytest
import yaml

from src.app.runtime.env_loading import load_project_env

PROJECT_ROOT = Path(__file__).parents[4]


@pytest.fixture
def env_files(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text(
        "SHARED_VAR=from_env\nBASE_ONLY=from_env\n"
    )
    (tmp_path / ".env.dev").write_text(
        "SHARED_VAR=from_env_dev\nDEV_ONLY_PLACEHOLDER=placeholder\n"
    )
    return tmp_path


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch):
    for var in (
        "SHARED_VAR",
        "BASE_ONLY",
        "DEV_ONLY_PLACEHOLDER",
        "APP_ENVIRONMENT",
    ):
        monkeypatch.delenv(var, raising=False)


class TestPrecedence:
    def test_development_loads_env_dev_over_env(self, env_files: Path) -> None:
        load_project_env(env_files, environment="development")
        assert os.environ["SHARED_VAR"] == "from_env_dev"
        assert os.environ["BASE_ONLY"] == "from_env"
        assert os.environ["DEV_ONLY_PLACEHOLDER"] == "placeholder"

    def test_non_development_skips_env_dev(self, env_files: Path) -> None:
        load_project_env(env_files, environment="production")
        assert os.environ["SHARED_VAR"] == "from_env"
        assert "DEV_ONLY_PLACEHOLDER" not in os.environ

    def test_environment_defaults_to_app_environment_var(
        self, env_files: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("APP_ENVIRONMENT", "development")
        load_project_env(env_files)
        assert os.environ["DEV_ONLY_PLACEHOLDER"] == "placeholder"

    def test_unset_environment_skips_env_dev(self, env_files: Path) -> None:
        load_project_env(env_files)
        assert "DEV_ONLY_PLACEHOLDER" not in os.environ

    def test_shell_wins_over_both_files(
        self, env_files: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SHARED_VAR", "from_shell")
        load_project_env(env_files, environment="development")
        assert os.environ["SHARED_VAR"] == "from_shell"

    def test_missing_files_are_tolerated(self, tmp_path: Path) -> None:
        load_project_env(tmp_path, environment="development")  # no raise


class TestComposeMirror:
    def test_dev_worker_env_file_order_mirrors_precedence(self) -> None:
        """Compose gives the LATER env_file precedence; .env.dev must
        therefore come after .env to match load_project_env."""
        compose = yaml.safe_load(
            (PROJECT_ROOT / "docker-compose.dev.yml").read_text()
        )
        env_file = compose["services"]["worker"]["env_file"]
        assert env_file == [".env", ".env.dev"]
