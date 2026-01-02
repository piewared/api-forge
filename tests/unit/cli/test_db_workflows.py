"""Tests for database workflow functions."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import typer

from src.cli.commands.db.runtime import DbRuntime, no_port_forward
from src.cli.commands.db.workflows import (
    run_backup,
    run_init,
    run_migrate,
    run_reset,
    run_status,
    run_sync,
    run_verify,
)


@pytest.fixture
def mock_runtime():
    """Create a mock DbRuntime for testing."""
    runtime = Mock(spec=DbRuntime)
    runtime.name = "test"
    runtime.console = Mock()
    runtime.get_settings = Mock()
    runtime.connect = Mock()
    runtime.port_forward = Mock(return_value=no_port_forward())
    runtime.get_deployer = Mock()
    runtime.secrets_dirs = [Path("/tmp")]
    runtime.is_temporal_enabled = Mock(return_value=False)
    runtime.is_bundled_postgres_enabled = Mock(return_value=False)
    return runtime


@pytest.fixture
def mock_connection():
    """Create a mock PostgresConnection."""
    conn = MagicMock()
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=False)
    conn.scalar = Mock()
    conn.get_connection_string = Mock(return_value="postgres://test")
    return conn


@pytest.fixture
def mock_settings():
    """Create mock database settings."""
    settings = Mock()
    settings.ensure_all_passwords = Mock(return_value=settings)
    settings.ensure_superuser_password = Mock(return_value=settings)
    settings.host = "localhost"
    settings.port = 5432
    settings.app_db = "appdb"
    return settings


def test_run_init_success(mock_runtime, mock_connection, mock_settings):
    """Test successful database initialization."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection

    with patch("src.infra.postgres.PostgresInitializer") as mock_init:
        mock_initializer = Mock()
        mock_initializer.initialize.return_value = True
        mock_init.return_value = mock_initializer

        result = run_init(mock_runtime)

        assert result is True
        mock_init.assert_called_once_with(connection=mock_connection)
        mock_initializer.initialize.assert_called_once()


def test_run_init_failure(mock_runtime, mock_connection, mock_settings):
    """Test failed database initialization."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection

    with patch("src.infra.postgres.PostgresInitializer") as mock_init:
        mock_initializer = Mock()
        mock_initializer.initialize.return_value = False
        mock_init.return_value = mock_initializer

        result = run_init(mock_runtime)

        assert result is False


def test_run_verify_with_superuser(mock_runtime, mock_connection, mock_settings):
    """Test database verification with superuser mode."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection

    with patch("src.infra.postgres.PostgresVerifier") as mock_verifier:
        mock_verifier_instance = Mock()
        mock_verifier_instance.verify_all.return_value = True
        mock_verifier.return_value = mock_verifier_instance

        result = run_verify(mock_runtime, superuser_mode=True)

        assert result is True
        mock_runtime.connect.assert_called_once_with(mock_settings, True)


def test_run_verify_without_superuser(mock_runtime, mock_connection, mock_settings):
    """Test database verification without superuser mode."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection

    with patch("src.infra.postgres.PostgresVerifier") as mock_verifier:
        mock_verifier_instance = Mock()
        mock_verifier_instance.verify_all.return_value = True
        mock_verifier.return_value = mock_verifier_instance

        result = run_verify(mock_runtime, superuser_mode=False)

        assert result is True
        mock_runtime.connect.assert_called_once_with(mock_settings, False)


def test_run_sync_with_bundled_postgres(mock_runtime, mock_connection, mock_settings):
    """Test password sync when bundled postgres is enabled."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection
    mock_runtime.is_bundled_postgres_enabled.return_value = True

    with patch("src.infra.postgres.PostgresPasswordSync") as mock_sync:
        mock_sync_instance = Mock()
        mock_sync_instance.sync_bundled_superuser_password.return_value = True
        mock_sync_instance.sync_user_roles_and_passwords.return_value = True
        mock_sync.return_value = mock_sync_instance

        result = run_sync(mock_runtime)

        assert result is True
        # Should be called twice - once for bundled, once for users
        assert mock_sync.call_count == 2
        mock_sync_instance.sync_bundled_superuser_password.assert_called_once()
        mock_sync_instance.sync_user_roles_and_passwords.assert_called_once()


def test_run_sync_without_bundled_postgres(
    mock_runtime, mock_connection, mock_settings
):
    """Test password sync when bundled postgres is disabled."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection
    mock_runtime.is_bundled_postgres_enabled.return_value = False

    with patch("src.infra.postgres.PostgresPasswordSync") as mock_sync:
        mock_sync_instance = Mock()
        mock_sync_instance.sync_user_roles_and_passwords.return_value = True
        mock_sync.return_value = mock_sync_instance

        result = run_sync(mock_runtime)

        assert result is True
        # Should only be called once for users
        mock_sync.assert_called_once()
        mock_sync_instance.sync_user_roles_and_passwords.assert_called_once()


def test_run_backup_success(mock_runtime, mock_connection, mock_settings):
    """Test successful database backup."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection

    with patch("src.infra.postgres.PostgresBackup") as mock_backup:
        mock_backup_instance = Mock()
        mock_backup_instance.create_backup.return_value = (True, "/path/to/backup.sql")
        mock_backup.return_value = mock_backup_instance

        output_dir = Path("/tmp/backups")
        success, result = run_backup(
            mock_runtime, output_dir=output_dir, superuser_mode=True
        )

        assert success is True
        assert result == "/path/to/backup.sql"
        mock_backup.assert_called_once_with(
            connection=mock_connection, backup_dir=output_dir
        )


def test_run_backup_failure(mock_runtime, mock_connection, mock_settings):
    """Test failed database backup."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection

    with patch("src.infra.postgres.PostgresBackup") as mock_backup:
        mock_backup_instance = Mock()
        mock_backup_instance.create_backup.return_value = (False, "Backup failed")
        mock_backup.return_value = mock_backup_instance

        success, result = run_backup(
            mock_runtime, output_dir=Path("/tmp"), superuser_mode=False
        )

        assert success is False
        assert result == "Backup failed"


def test_run_reset_with_temporal(mock_runtime, mock_connection, mock_settings):
    """Test database reset including temporal."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection

    with patch("src.infra.postgres.PostgresReset") as mock_reset:
        mock_reset_instance = Mock()
        mock_reset_instance.reset.return_value = True
        mock_reset.return_value = mock_reset_instance

        result = run_reset(mock_runtime, include_temporal=True, superuser_mode=True)

        assert result is True
        mock_reset_instance.reset.assert_called_once_with(include_temporal=True)


def test_run_reset_without_temporal(mock_runtime, mock_connection, mock_settings):
    """Test database reset excluding temporal."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection

    with patch("src.infra.postgres.PostgresReset") as mock_reset:
        mock_reset_instance = Mock()
        mock_reset_instance.reset.return_value = True
        mock_reset.return_value = mock_reset_instance

        result = run_reset(mock_runtime, include_temporal=False, superuser_mode=False)

        assert result is True
        mock_reset_instance.reset.assert_called_once_with(include_temporal=False)


def test_run_status_displays_metrics(mock_runtime, mock_connection, mock_settings):
    """Test that status command displays database metrics."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection
    mock_runtime.is_temporal_enabled.return_value = False

    # Mock scalar queries
    mock_connection.scalar.side_effect = [
        3600.0,  # uptime
        5,  # active connections
        10,  # total connections
        100,  # max connections
        95.5,  # cache hit ratio
        "100 MB",  # database size
        5,  # table count
        1000,  # row count
    ]

    run_status(mock_runtime, superuser_mode=True)

    # Verify output was printed
    assert mock_runtime.console.print.called


def test_run_status_handles_connection_error(mock_runtime, mock_settings):
    """Test that status command handles connection errors gracefully."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.side_effect = Exception("Connection failed")

    # Should not raise, should handle gracefully
    run_status(mock_runtime, superuser_mode=False)

    mock_runtime.console.error.assert_called()


def test_run_migrate_success(mock_runtime, mock_connection, mock_settings):
    """Test successful migration execution."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection

    with patch("src.cli.commands.db.workflows.run_migration") as mock_migrate:
        mock_migrate.return_value = True

        # Should not raise
        run_migrate(
            mock_runtime,
            action="upgrade",
            revision="head",
            message=None,
            merge_revisions=[],
            purge=False,
            autogenerate=False,
            sql=False,
        )

        mock_migrate.assert_called_once()
        call_kwargs = mock_migrate.call_args.kwargs
        assert call_kwargs["action"] == "upgrade"
        assert call_kwargs["revision"] == "head"
        assert call_kwargs["database_url"] == "postgres://test"


def test_run_migrate_failure_raises_exit(mock_runtime, mock_connection, mock_settings):
    """Test that migration failure raises typer.Exit."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection

    with patch("src.cli.commands.db.workflows.run_migration") as mock_migrate:
        mock_migrate.return_value = False

        with pytest.raises(typer.Exit) as exc_info:
            run_migrate(
                mock_runtime,
                action="upgrade",
                revision=None,
                message="test migration",
                merge_revisions=[],
                purge=False,
                autogenerate=True,
                sql=False,
            )

        assert exc_info.value.exit_code == 1


def test_workflows_use_port_forward_context(
    mock_runtime, mock_connection, mock_settings
):
    """Test that all workflows properly use port_forward context manager."""
    mock_runtime.get_settings.return_value = mock_settings
    mock_runtime.connect.return_value = mock_connection

    # Track if port_forward context was entered
    port_forward_entered = False

    def track_port_forward():
        nonlocal port_forward_entered
        port_forward_entered = True
        return no_port_forward()

    mock_runtime.port_forward = track_port_forward

    with patch("src.infra.postgres.PostgresInitializer") as mock_init:
        mock_init.return_value.initialize.return_value = True
        run_init(mock_runtime)
        assert port_forward_entered

    port_forward_entered = False
    with patch("src.infra.postgres.PostgresVerifier") as mock_verify:
        mock_verify.return_value.verify_all.return_value = True
        run_verify(mock_runtime, superuser_mode=True)
        assert port_forward_entered
