"""Unit tests for src/cli/shared/fly.py prerequisite helpers."""

from unittest.mock import MagicMock, patch

import pytest
import typer

from src.cli.shared.fly import (
    check_authenticated,
    check_flyctl_installed,
    check_prerequisites,
    get_fly_controller,
)
from src.infra.flyio import FlyCtlControllerSync


class TestGetFlyController:
    """Tests for get_fly_controller factory."""

    def test_returns_sync_controller(self) -> None:
        """get_fly_controller must return a FlyCtlControllerSync instance."""
        controller = get_fly_controller()
        assert isinstance(controller, FlyCtlControllerSync)


class TestCheckFlyctlInstalled:
    """Tests for check_flyctl_installed."""

    def test_passes_when_installed(self) -> None:
        """No exception is raised when flyctl is installed."""
        controller = MagicMock()
        controller.is_installed.return_value = True
        # Should not raise
        check_flyctl_installed(controller)

    def test_raises_when_missing(self) -> None:
        """Raises typer.Exit when flyctl is not installed."""
        controller = MagicMock()
        controller.is_installed.return_value = False

        with pytest.raises(typer.Exit):
            check_flyctl_installed(controller)


class TestCheckAuthenticated:
    """Tests for check_authenticated."""

    def test_passes_when_authenticated(self) -> None:
        """No exception is raised when the user is authenticated."""
        controller = MagicMock()
        controller.is_authenticated.return_value = True
        # Should not raise
        check_authenticated(controller)

    def test_raises_when_not_logged_in(self) -> None:
        """Raises typer.Exit when the user is not authenticated."""
        controller = MagicMock()
        controller.is_authenticated.return_value = False

        with pytest.raises(typer.Exit):
            check_authenticated(controller)


class TestCheckPrerequisites:
    """Tests for check_prerequisites."""

    def test_calls_both_checks(self) -> None:
        """check_prerequisites delegates to both sub-checks."""
        controller = MagicMock()

        with (
            patch("src.cli.shared.fly.check_flyctl_installed") as mock_installed,
            patch("src.cli.shared.fly.check_authenticated") as mock_auth,
        ):
            check_prerequisites(controller)

        mock_installed.assert_called_once_with(controller)
        mock_auth.assert_called_once_with(controller)

    def test_stops_at_first_failure(self) -> None:
        """If check_flyctl_installed raises, check_authenticated is not called."""
        controller = MagicMock()

        with (
            patch(
                "src.cli.shared.fly.check_flyctl_installed",
                side_effect=typer.Exit(1),
            ) as mock_installed,
            patch("src.cli.shared.fly.check_authenticated") as mock_auth,
        ):
            with pytest.raises(typer.Exit):
                check_prerequisites(controller)

        mock_installed.assert_called_once_with(controller)
        mock_auth.assert_not_called()
