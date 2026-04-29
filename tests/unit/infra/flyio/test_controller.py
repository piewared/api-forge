"""Unit tests for Fly.io controller."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infra.flyio.controller import (
    BackupInfo,
    CommandResult,
    FlyAppInfo,
    FlyCtlController,
    FlyCtlControllerSync,
    ManagedPostgresInfo,
)


class TestFlyCtlController:
    """Tests for FlyCtlController async methods."""

    @pytest.fixture
    def controller(self) -> FlyCtlController:
        """Create a controller instance."""
        return FlyCtlController()

    @pytest.mark.asyncio
    async def test_is_installed_with_fly(self, controller: FlyCtlController) -> None:
        """Test is_installed when fly command exists."""
        with patch("shutil.which", return_value="/usr/bin/fly"):
            result = await controller.is_installed()
            assert result is True

    @pytest.mark.asyncio
    async def test_is_installed_with_only_flyctl_returns_false(
        self, controller: FlyCtlController
    ) -> None:
        """If only ``flyctl`` is on PATH (and not ``fly``), is_installed must
        report False — _run_flyctl invokes ``fly`` specifically, so accepting
        a flyctl-only environment would let every later command fail with
        FileNotFoundError instead of producing a clear up-front error."""

        def mock_which(cmd: str) -> str | None:
            return "/usr/bin/flyctl" if cmd == "flyctl" else None

        with patch("shutil.which", side_effect=mock_which):
            result = await controller.is_installed()
            assert result is False

    @pytest.mark.asyncio
    async def test_is_installed_not_found(self, controller: FlyCtlController) -> None:
        """Test is_installed when neither command exists."""
        with patch("shutil.which", return_value=None):
            result = await controller.is_installed()
            assert result is False

    @pytest.mark.asyncio
    async def test_auth_whoami_authenticated(
        self, controller: FlyCtlController
    ) -> None:
        """Test auth_whoami when authenticated."""
        mock_result = CommandResult(
            success=True,
            stdout="test@example.com\n",
            stderr="",
            returncode=0,
        )
        with patch.object(controller, "_run_flyctl", return_value=mock_result):
            is_auth, email = await controller.auth_whoami()
            assert is_auth is True
            assert email == "test@example.com"

    @pytest.mark.asyncio
    async def test_auth_whoami_not_authenticated(
        self, controller: FlyCtlController
    ) -> None:
        """Test auth_whoami when not authenticated."""
        mock_result = CommandResult(
            success=False,
            stdout="",
            stderr="not logged in",
            returncode=1,
        )
        with patch.object(controller, "_run_flyctl", return_value=mock_result):
            is_auth, message = await controller.auth_whoami()
            assert is_auth is False
            assert message == "not logged in"

    @pytest.mark.asyncio
    async def test_is_authenticated(self, controller: FlyCtlController) -> None:
        """Test is_authenticated helper method."""
        with patch.object(
            controller, "auth_whoami", return_value=(True, "test@example.com")
        ):
            result = await controller.is_authenticated()
            assert result is True

    @pytest.mark.asyncio
    async def test_mpg_list_success(self, controller: FlyCtlController) -> None:
        """Test mpg_list with successful response."""
        mock_clusters = [
            {
                "id": "cluster-1",
                "name": "my-postgres",
                "region": "iad",
                "plan": "basic",
                "status": "running",
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "id": "cluster-2",
                "name": "other-postgres",
                "region": "lhr",
                "plan": "development",
                "status": "running",
                "created_at": "2024-01-02T00:00:00Z",
            },
        ]
        with patch.object(
            controller, "_run_flyctl_json", return_value=(True, mock_clusters)
        ):
            result = await controller.mpg_list()
            assert len(result) == 2
            assert isinstance(result[0], ManagedPostgresInfo)
            assert result[0].name == "my-postgres"
            assert result[0].region == "iad"
            assert result[1].name == "other-postgres"

    @pytest.mark.asyncio
    async def test_mpg_list_empty(self, controller: FlyCtlController) -> None:
        """Test mpg_list with empty response."""
        with patch.object(controller, "_run_flyctl_json", return_value=(True, [])):
            result = await controller.mpg_list()
            assert result == []

    @pytest.mark.asyncio
    async def test_mpg_list_failure(self, controller: FlyCtlController) -> None:
        """Test mpg_list with failed response."""
        with patch.object(controller, "_run_flyctl_json", return_value=(False, None)):
            result = await controller.mpg_list()
            assert result == []

    @pytest.mark.asyncio
    async def test_mpg_status_success(self, controller: FlyCtlController) -> None:
        """Test mpg_status with successful response."""
        mock_status = {
            "id": "cluster-1",
            "name": "my-postgres",
            "region": "iad",
            "plan": "basic",
            "status": "running",
            "created_at": "2024-01-01T00:00:00Z",
            "connection_string": "postgres://user:pass@host:5432/db",
        }
        with patch.object(
            controller, "_run_flyctl_json", return_value=(True, mock_status)
        ):
            result = await controller.mpg_status("cluster-1")
            assert result is not None
            assert result.name == "my-postgres"
            assert result.connection_string == "postgres://user:pass@host:5432/db"

    @pytest.mark.asyncio
    async def test_mpg_status_not_found(self, controller: FlyCtlController) -> None:
        """Test mpg_status when cluster not found."""
        with patch.object(controller, "_run_flyctl_json", return_value=(False, None)):
            result = await controller.mpg_status("nonexistent")
            assert result is None

    @pytest.mark.asyncio
    async def test_mpg_create(self, controller: FlyCtlController) -> None:
        """Test mpg_create command construction."""
        mock_result = CommandResult(success=True, stdout="Created", returncode=0)

        with patch.object(
            controller, "_run_flyctl", return_value=mock_result
        ) as mock_run:
            result = await controller.mpg_create(
                name="test-db",
                region="iad",
                plan="basic",
                volume_size=20,
                enable_postgis=True,
            )

            assert result.success is True
            # Verify the command was called with correct arguments
            call_args = mock_run.call_args[0][0]
            assert "mpg" in call_args
            assert "create" in call_args
            assert "--name" in call_args
            assert "test-db" in call_args
            assert "--region" in call_args
            assert "iad" in call_args
            assert "--enable-postgis-support" in call_args

    @pytest.mark.asyncio
    async def test_secrets_list_success(self, controller: FlyCtlController) -> None:
        """Test secrets_list parsing."""
        mock_result = CommandResult(
            success=True,
            stdout="NAME        | DIGEST   | DATE\nDATABASE_URL | abc123  | 2024-01-01\nREDIS_URL   | def456  | 2024-01-01\n",
            returncode=0,
        )
        with patch.object(controller, "_run_flyctl", return_value=mock_result):
            result = await controller.secrets_list("my-app")
            assert "DATABASE_URL" in result
            assert "REDIS_URL" in result

    @pytest.mark.asyncio
    async def test_apps_list_success(self, controller: FlyCtlController) -> None:
        """Test apps_list with successful response."""
        mock_apps = [
            {
                "Name": "my-app",
                "Organization": {"Slug": "personal"},
                "Status": "deployed",
                "Hostname": "my-app.fly.dev",
            }
        ]
        with patch.object(
            controller, "_run_flyctl_json", return_value=(True, mock_apps)
        ):
            result = await controller.apps_list()
            assert len(result) == 1
            assert isinstance(result[0], FlyAppInfo)
            assert result[0].name == "my-app"

    @pytest.mark.asyncio
    async def test_mpg_backup_list_success(self, controller: FlyCtlController) -> None:
        """Test mpg_backup_list with successful response."""
        mock_backups = [
            {
                "id": "backup-1",
                "status": "completed",
                "created_at": "2024-01-01T00:00:00Z",
                "size_bytes": 1024000,
            }
        ]
        with patch.object(
            controller, "_run_flyctl_json", return_value=(True, mock_backups)
        ):
            result = await controller.mpg_backup_list("cluster-1")
            assert len(result) == 1
            assert isinstance(result[0], BackupInfo)
            assert result[0].id == "backup-1"


class TestFlyCtlControllerSync:
    """Tests for FlyCtlControllerSync wrapper."""

    def test_sync_wrapper_wraps_async_methods(self) -> None:
        """Test that sync wrapper correctly wraps async methods."""
        sync_controller = FlyCtlControllerSync()

        # Mock the underlying async controller's method
        with patch.object(
            sync_controller._controller, "is_installed", new_callable=AsyncMock
        ) as mock:
            mock.return_value = True
            result = sync_controller.is_installed()
            assert result is True
            mock.assert_called_once()

    def test_sync_wrapper_auth_whoami(self) -> None:
        """Test sync wrapper for auth_whoami."""
        sync_controller = FlyCtlControllerSync()

        with patch.object(
            sync_controller._controller, "auth_whoami", new_callable=AsyncMock
        ) as mock:
            mock.return_value = (True, "test@example.com")
            is_auth, email = sync_controller.auth_whoami()
            assert is_auth is True
            assert email == "test@example.com"

    def test_sync_wrapper_mpg_list(self) -> None:
        """Test sync wrapper for mpg_list."""
        sync_controller = FlyCtlControllerSync()

        mock_info = ManagedPostgresInfo(
            id="1", name="test", region="iad", plan="basic", status="running"
        )
        with patch.object(
            sync_controller._controller, "mpg_list", new_callable=AsyncMock
        ) as mock:
            mock.return_value = [mock_info]
            result = sync_controller.mpg_list()
            assert len(result) == 1
            assert result[0].name == "test"
