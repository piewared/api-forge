"""Unit tests for Fly.io authentication CLI commands."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.cli.commands.fly_auth import fly_auth_app
from src.infra.flyio.controller import CommandResult

runner = CliRunner()


@pytest.fixture
def fly_controller() -> MagicMock:
    """Mock flyctl controller. Defaults to flyctl being installed."""
    controller = MagicMock()
    controller.is_installed.return_value = True
    return controller


@pytest.fixture(autouse=True)
def patch_get_fly_controller(
    fly_controller: MagicMock,
) -> Generator[None]:
    """The CLI commands resolve the controller via get_fly_controller; replace
    it with the test mock for every test in this module."""
    with patch(
        "src.cli.commands.fly_auth.get_fly_controller", return_value=fly_controller
    ):
        yield


class TestWhoami:
    def test_authenticated_prints_email(self, fly_controller: MagicMock) -> None:
        fly_controller.auth_whoami.return_value = (True, "test@example.com")

        result = runner.invoke(fly_auth_app, ["whoami"])

        assert result.exit_code == 0
        assert "test@example.com" in result.stdout

    def test_unauthenticated_exits_nonzero(self, fly_controller: MagicMock) -> None:
        fly_controller.auth_whoami.return_value = (False, "not logged in")

        result = runner.invoke(fly_auth_app, ["whoami"])

        assert result.exit_code == 1
        assert "Not logged in" in result.stdout

    def test_flyctl_not_installed(self, fly_controller: MagicMock) -> None:
        fly_controller.is_installed.return_value = False

        result = runner.invoke(fly_auth_app, ["whoami"])

        assert result.exit_code == 1
        assert "not installed" in result.stdout


class TestStatus:
    def test_authenticated(self, fly_controller: MagicMock) -> None:
        fly_controller.auth_whoami.return_value = (True, "test@example.com")
        fly_controller.auth_token.return_value = (True, "some-token")

        result = runner.invoke(fly_auth_app, ["status"])

        assert result.exit_code == 0
        assert "Authenticated" in result.stdout

    def test_unauthenticated(self, fly_controller: MagicMock) -> None:
        fly_controller.auth_whoami.return_value = (False, "not logged in")

        result = runner.invoke(fly_auth_app, ["status"])

        assert result.exit_code == 0
        assert "Not authenticated" in result.stdout


class TestLogout:
    def test_when_logged_in(self, fly_controller: MagicMock) -> None:
        fly_controller.auth_whoami.return_value = (True, "test@example.com")
        fly_controller.auth_logout.return_value = CommandResult(success=True)

        result = runner.invoke(fly_auth_app, ["logout"])

        assert result.exit_code == 0
        assert "Successfully logged out" in result.stdout

    def test_when_not_logged_in(self, fly_controller: MagicMock) -> None:
        fly_controller.auth_whoami.return_value = (False, "not logged in")

        result = runner.invoke(fly_auth_app, ["logout"])

        assert result.exit_code == 0
        assert "Not currently logged in" in result.stdout


class TestLogin:
    def test_already_logged_in_user_declines_switch(
        self, fly_controller: MagicMock
    ) -> None:
        fly_controller.auth_whoami.return_value = (True, "test@example.com")

        # User answers "no" to the switch prompt.
        result = runner.invoke(fly_auth_app, ["login"], input="n\n")

        assert result.exit_code == 0
        assert "Already logged in" in result.stdout

    def test_success(self, fly_controller: MagicMock) -> None:
        # whoami: not logged in pre-login, logged in post-login.
        fly_controller.auth_whoami.side_effect = [
            (False, "not logged in"),
            (True, "test@example.com"),
        ]
        fly_controller.auth_login.return_value = CommandResult(success=True)

        result = runner.invoke(fly_auth_app, ["login"])

        assert result.exit_code == 0
        assert "Successfully logged in" in result.stdout
