"""Unit tests for fly_db workflow CLI commands (init, verify, migrate, backup)."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.cli.commands.fly_db import fly_db_app
from src.cli.commands.fly_db.select import SelectedCluster
from src.infra.flyio.controller import CommandResult

runner = CliRunner()

_WORKFLOWS_MOD = "src.cli.commands.fly_db.workflows"


def _fake_cluster() -> SelectedCluster:
    return SelectedCluster(
        id="cid-1",
        name="test-db",
        region="iad",
        status="running",
        plan="basic",
        is_legacy=False,
    )


@pytest.fixture
def fly_controller() -> MagicMock:
    """The flyctl controller mock — tests configure it as needed."""
    return MagicMock()


@pytest.fixture(autouse=True)
def patch_workflow_prerequisites(
    fly_controller: MagicMock,
) -> Generator[None]:
    """Patch the four collaborators every fly_db CLI command resolves before
    delegating to its run_* function.

    The CLI command itself is what's under test; we don't want to drag in real
    flyctl invocations, prerequisite checks, cluster selection, or runtime
    construction. Tests still patch the specific run_* function they assert on.
    """
    with ExitStack() as stack:
        stack.enter_context(
            patch(f"{_WORKFLOWS_MOD}.get_fly_controller", return_value=fly_controller)
        )
        stack.enter_context(patch(f"{_WORKFLOWS_MOD}.check_prerequisites"))
        stack.enter_context(
            patch(f"{_WORKFLOWS_MOD}._select_cluster", return_value=_fake_cluster())
        )
        stack.enter_context(
            patch(f"{_WORKFLOWS_MOD}._get_runtime", return_value=MagicMock())
        )
        yield


class TestMigrateCommand:
    def test_migrate_invokes_run_migrate(self) -> None:
        with patch(f"{_WORKFLOWS_MOD}.run_migrate") as mock_run_migrate:
            result = runner.invoke(fly_db_app, ["migrate"])

        assert result.exit_code == 0
        mock_run_migrate.assert_called_once()
        assert mock_run_migrate.call_args.kwargs["action"] == "upgrade"


_HELPERS_MOD = "src.cli.commands.db.cli_helpers"


class TestInitCommand:
    def test_init_invokes_run_init(self) -> None:
        # The fly_db init command now goes through execute_init (in cli_helpers),
        # which calls run_init. Patch the underlying workflow at its
        # canonical location so this test still asserts wiring.
        with patch(f"{_HELPERS_MOD}.run_init", return_value=True) as mock_run_init:
            result = runner.invoke(fly_db_app, ["init"])

        assert result.exit_code == 0
        mock_run_init.assert_called_once()


class TestVerifyCommand:
    def test_verify_invokes_run_verify(self) -> None:
        with patch(f"{_HELPERS_MOD}.run_verify", return_value=True) as mock_run_verify:
            result = runner.invoke(fly_db_app, ["verify"])

        assert result.exit_code == 0
        mock_run_verify.assert_called_once()


class TestBackupCommand:
    def test_backup_default_invokes_run_backup(self, tmp_path) -> None:
        """Without --mpg-backup, the backup command delegates to run_backup."""
        with patch(
            f"{_WORKFLOWS_MOD}.run_backup",
            return_value=(True, tmp_path / "dump.sql"),
        ) as mock_run_backup:
            # --output avoids importing get_project_root at runtime.
            result = runner.invoke(fly_db_app, ["backup", "--output", str(tmp_path)])

        assert result.exit_code == 0
        mock_run_backup.assert_called_once()

    def test_backup_mpg_path_invokes_controller(
        self, fly_controller: MagicMock
    ) -> None:
        """--mpg-backup calls controller.mpg_backup_create directly."""
        fly_controller.mpg_backup_create.return_value = CommandResult(success=True)

        with patch(f"{_WORKFLOWS_MOD}.run_backup") as mock_run_backup:
            result = runner.invoke(fly_db_app, ["backup", "--mpg-backup"])

        assert result.exit_code == 0
        fly_controller.mpg_backup_create.assert_called_once()
        mock_run_backup.assert_not_called()
