"""Unit tests for src/cli/shared/fly.py prerequisite helpers."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer

from src.cli.shared.fly import (
    _get_cached_latest_flyctl_version,
    _get_current_flyctl_version,
    _parse_version,
    _should_show_version_warning,
    check_authenticated,
    check_flyctl_installed,
    check_flyctl_version,
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

    def test_calls_all_checks(self) -> None:
        """check_prerequisites delegates to install + auth + version check."""
        controller = MagicMock()

        with (
            patch("src.cli.shared.fly.check_flyctl_installed") as mock_installed,
            patch("src.cli.shared.fly.check_authenticated") as mock_auth,
            patch("src.cli.shared.fly.check_flyctl_version") as mock_version,
        ):
            check_prerequisites(controller)

        mock_installed.assert_called_once_with(controller)
        mock_auth.assert_called_once_with(controller)
        mock_version.assert_called_once_with()

    def test_stops_at_first_failure(self) -> None:
        """If check_flyctl_installed raises, the rest are not called."""
        controller = MagicMock()

        with (
            patch(
                "src.cli.shared.fly.check_flyctl_installed",
                side_effect=typer.Exit(1),
            ) as mock_installed,
            patch("src.cli.shared.fly.check_authenticated") as mock_auth,
            patch("src.cli.shared.fly.check_flyctl_version") as mock_version,
        ):
            with pytest.raises(typer.Exit):
                check_prerequisites(controller)

        mock_installed.assert_called_once_with(controller)
        mock_auth.assert_not_called()
        mock_version.assert_not_called()


class TestParseVersion:
    """Tests for the lenient version parser."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("0.4.43", (0, 4, 43)),
            ("v0.4.43", (0, 4, 43)),
            ("V1.2.3", (1, 2, 3)),
            ("0.4.43-pre1", (0, 4, 43)),
            ("0.4.43+abc.def", (0, 4, 43)),
            ("  0.4.43  ", (0, 4, 43)),
        ],
    )
    def test_parses_valid_versions(
        self, raw: str, expected: tuple[int, int, int]
    ) -> None:
        assert _parse_version(raw) == expected

    @pytest.mark.parametrize("raw", ["", "0.4", "abc", "0.4.x", "0..4"])
    def test_returns_none_for_invalid(self, raw: str) -> None:
        assert _parse_version(raw) is None


class TestGetCurrentFlyctlVersion:
    """Tests for the subprocess-driven current-version probe."""

    def test_parses_capitalised_key(self) -> None:
        result = MagicMock(returncode=0, stdout=json.dumps({"Version": "0.4.43"}))
        with patch("subprocess.run", return_value=result):
            assert _get_current_flyctl_version() == (0, 4, 43)

    def test_parses_lowercase_key(self) -> None:
        result = MagicMock(returncode=0, stdout=json.dumps({"version": "1.2.3"}))
        with patch("subprocess.run", return_value=result):
            assert _get_current_flyctl_version() == (1, 2, 3)

    def test_returns_none_on_nonzero_exit(self) -> None:
        result = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=result):
            assert _get_current_flyctl_version() is None

    def test_returns_none_on_invalid_json(self) -> None:
        result = MagicMock(returncode=0, stdout="not json")
        with patch("subprocess.run", return_value=result):
            assert _get_current_flyctl_version() is None

    def test_returns_none_on_oserror(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError("no fly")):
            assert _get_current_flyctl_version() is None


class TestGetCachedLatestFlyctlVersion:
    """Tests for reading flyctl's own state cache."""

    def test_reads_latest_release_version(self, tmp_path: Path) -> None:
        state = tmp_path / ".fly" / "state.json"
        state.parent.mkdir()
        state.write_text(json.dumps({"latest_release_version": "0.4.50"}))

        with patch("src.cli.shared.fly.Path.home", return_value=tmp_path):
            assert _get_cached_latest_flyctl_version() == (0, 4, 50)

    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        with patch("src.cli.shared.fly.Path.home", return_value=tmp_path):
            assert _get_cached_latest_flyctl_version() is None

    def test_returns_none_when_key_missing(self, tmp_path: Path) -> None:
        state = tmp_path / ".fly" / "state.json"
        state.parent.mkdir()
        state.write_text(json.dumps({"unrelated": "data"}))

        with patch("src.cli.shared.fly.Path.home", return_value=tmp_path):
            assert _get_cached_latest_flyctl_version() is None


class TestVersionWarningTimeGate:
    """Tests for the once-per-week nag timer."""

    def test_warns_when_marker_missing(self, tmp_path: Path) -> None:
        marker = tmp_path / "nag-marker"
        with patch("src.cli.shared.fly._NAG_MARKER_PATH", marker):
            assert _should_show_version_warning() is True

    def test_suppresses_within_interval(self, tmp_path: Path) -> None:
        import time as _time

        marker = tmp_path / "nag-marker"
        marker.write_text("")
        # Set mtime to "30 minutes ago" — well inside the 7-day interval.
        recent = _time.time() - 30 * 60
        import os as _os

        _os.utime(marker, (recent, recent))
        with patch("src.cli.shared.fly._NAG_MARKER_PATH", marker):
            assert _should_show_version_warning() is False

    def test_warns_when_interval_elapsed(self, tmp_path: Path) -> None:
        import os as _os
        import time as _time

        marker = tmp_path / "nag-marker"
        marker.write_text("")
        # Set mtime to 8 days ago — past the 7-day window.
        old = _time.time() - 8 * 24 * 3600
        _os.utime(marker, (old, old))
        with patch("src.cli.shared.fly._NAG_MARKER_PATH", marker):
            assert _should_show_version_warning() is True


class TestCheckFlyctlVersion:
    """Tests for the orchestrating check_flyctl_version helper."""

    def test_silent_when_current_meets_recommendation(self, tmp_path: Path) -> None:
        """No warn when running version >= recommendation."""
        marker = tmp_path / "nag-marker"
        with (
            patch("src.cli.shared.fly._NAG_MARKER_PATH", marker),
            patch(
                "src.cli.shared.fly._get_current_flyctl_version",
                return_value=(99, 0, 0),
            ),
            patch(
                "src.cli.shared.fly._get_cached_latest_flyctl_version",
                return_value=None,
            ),
            patch("src.cli.shared.fly.console.warn") as mock_warn,
        ):
            check_flyctl_version()
            mock_warn.assert_not_called()
            assert not marker.exists()  # marker only set when we actually warn

    def test_warns_and_records_when_outdated(self, tmp_path: Path) -> None:
        marker = tmp_path / "nag-marker"
        with (
            patch("src.cli.shared.fly._NAG_MARKER_PATH", marker),
            patch(
                "src.cli.shared.fly._get_current_flyctl_version",
                return_value=(0, 1, 0),
            ),
            patch(
                "src.cli.shared.fly._get_cached_latest_flyctl_version",
                return_value=None,
            ),
            patch("src.cli.shared.fly.console.warn") as mock_warn,
        ):
            check_flyctl_version()
            mock_warn.assert_called_once()
            assert marker.exists()  # marker recorded so we don't nag again

    def test_silent_when_current_unknown(self, tmp_path: Path) -> None:
        """If `fly version` failed to parse, skip silently — no false warnings."""
        marker = tmp_path / "nag-marker"
        with (
            patch("src.cli.shared.fly._NAG_MARKER_PATH", marker),
            patch(
                "src.cli.shared.fly._get_current_flyctl_version",
                return_value=None,
            ),
            patch("src.cli.shared.fly.console.warn") as mock_warn,
        ):
            check_flyctl_version()
            mock_warn.assert_not_called()
