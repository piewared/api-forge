"""Tests for Helm rollback and history commands."""

from unittest.mock import MagicMock

import pytest

from src.cli.deployment.shell_commands.helm import HelmCommands
from src.cli.deployment.shell_commands.types import CommandResult


class TestHelmRollback:
    """Tests for Helm rollback command."""

    @pytest.fixture
    def mock_runner(self) -> MagicMock:
        """Create a mock command runner."""
        return MagicMock()

    @pytest.fixture
    def helm_commands(self, mock_runner: MagicMock) -> HelmCommands:
        """Create HelmCommands instance with mock runner."""
        return HelmCommands(mock_runner)

    def test_rollback_to_previous_revision(
        self, helm_commands: HelmCommands, mock_runner: MagicMock
    ) -> None:
        """Rollback without revision should rollback to previous."""
        mock_runner.run.return_value = CommandResult(
            success=True, stdout="Rollback was a success!", stderr="", returncode=0
        )

        result = helm_commands.rollback("my-release", "my-namespace")

        assert result.success
        mock_runner.run.assert_called_once()
        cmd = mock_runner.run.call_args[0][0]
        assert "helm" in cmd
        assert "rollback" in cmd
        assert "my-release" in cmd
        assert "-n" in cmd
        assert "my-namespace" in cmd
        # No revision number when rolling back to previous
        assert "--wait" in cmd

    def test_rollback_to_specific_revision(
        self, helm_commands: HelmCommands, mock_runner: MagicMock
    ) -> None:
        """Rollback with revision should target that specific revision."""
        mock_runner.run.return_value = CommandResult(
            success=True, stdout="Rollback was a success!", stderr="", returncode=0
        )

        result = helm_commands.rollback("my-release", "my-namespace", revision=3)

        assert result.success
        cmd = mock_runner.run.call_args[0][0]
        assert "3" in cmd

    def test_rollback_with_custom_timeout(
        self, helm_commands: HelmCommands, mock_runner: MagicMock
    ) -> None:
        """Rollback should use custom timeout when specified."""
        mock_runner.run.return_value = CommandResult(
            success=True, stdout="", stderr="", returncode=0
        )

        helm_commands.rollback("my-release", "my-namespace", revision=2, timeout="10m")

        cmd = mock_runner.run.call_args[0][0]
        assert "--timeout" in cmd
        assert "10m" in cmd

    def test_rollback_without_wait(
        self, helm_commands: HelmCommands, mock_runner: MagicMock
    ) -> None:
        """Rollback with wait=False should not include --wait flag."""
        mock_runner.run.return_value = CommandResult(
            success=True, stdout="", stderr="", returncode=0
        )

        helm_commands.rollback("my-release", "my-namespace", wait=False)

        cmd = mock_runner.run.call_args[0][0]
        assert "--wait" not in cmd


class TestHelmHistory:
    """Tests for Helm history command."""

    @pytest.fixture
    def mock_runner(self) -> MagicMock:
        """Create a mock command runner."""
        return MagicMock()

    @pytest.fixture
    def helm_commands(self, mock_runner: MagicMock) -> HelmCommands:
        """Create HelmCommands instance with mock runner."""
        return HelmCommands(mock_runner)

    def test_history_returns_parsed_json(
        self, helm_commands: HelmCommands, mock_runner: MagicMock
    ) -> None:
        """History should parse JSON response correctly."""
        history_json = """[
            {"revision": "3", "updated": "2025-01-01 12:00:00", "status": "deployed", "description": "Upgrade complete"},
            {"revision": "2", "updated": "2024-12-01 10:00:00", "status": "superseded", "description": "Upgrade complete"},
            {"revision": "1", "updated": "2024-11-01 08:00:00", "status": "superseded", "description": "Install complete"}
        ]"""
        mock_runner.run.return_value = CommandResult(
            success=True, stdout=history_json, stderr="", returncode=0
        )

        result = helm_commands.history("my-release", "my-namespace")

        assert len(result) == 3
        assert result[0]["revision"] == "3"
        assert result[0]["status"] == "deployed"

    def test_history_with_max_revisions(
        self, helm_commands: HelmCommands, mock_runner: MagicMock
    ) -> None:
        """History should respect max_revisions parameter."""
        mock_runner.run.return_value = CommandResult(
            success=True, stdout="[]", stderr="", returncode=0
        )

        helm_commands.history("my-release", "my-namespace", max_revisions=5)

        cmd = mock_runner.run.call_args[0][0]
        assert "--max" in cmd
        assert "5" in cmd

    def test_history_returns_empty_on_failure(
        self, helm_commands: HelmCommands, mock_runner: MagicMock
    ) -> None:
        """History should return empty list on command failure."""
        mock_runner.run.return_value = CommandResult(
            success=False, stdout="", stderr="Error", returncode=1
        )

        result = helm_commands.history("my-release", "my-namespace")

        assert result == []

    def test_history_returns_empty_on_invalid_json(
        self, helm_commands: HelmCommands, mock_runner: MagicMock
    ) -> None:
        """History should return empty list on invalid JSON."""
        mock_runner.run.return_value = CommandResult(
            success=True, stdout="not valid json", stderr="", returncode=0
        )

        result = helm_commands.history("my-release", "my-namespace")

        assert result == []

    def test_history_command_format(
        self, helm_commands: HelmCommands, mock_runner: MagicMock
    ) -> None:
        """History command should use correct format."""
        mock_runner.run.return_value = CommandResult(
            success=True, stdout="[]", stderr="", returncode=0
        )

        helm_commands.history("api-forge", "api-forge-prod")

        cmd = mock_runner.run.call_args[0][0]
        assert cmd == [
            "helm",
            "history",
            "api-forge",
            "-n",
            "api-forge-prod",
            "-o",
            "json",
            "--max",
            "10",
        ]
