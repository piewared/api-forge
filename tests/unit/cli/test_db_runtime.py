"""Tests for database runtime adapters."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.cli.commands.db.runtime import DbRuntime, no_port_forward


def test_no_port_forward_is_noop_context_manager():
    """Test that no_port_forward returns a no-op context manager."""
    with no_port_forward() as result:
        assert result is None


def test_db_runtime_is_immutable():
    """Test that DbRuntime is frozen/immutable."""
    runtime = DbRuntime(
        name="test",
        console=Mock(),
        get_settings=Mock(),
        connect=Mock(),
        port_forward=Mock(),
        get_deployer=Mock(),
        secrets_dirs=[Path("/tmp")],
        is_temporal_enabled=Mock(),
        is_bundled_postgres_enabled=Mock(),
    )

    with pytest.raises(AttributeError):
        runtime.name = "changed"  # type: ignore[attr-defined]


@patch("src.cli.commands.db.runtime_compose.get_settings")
@patch("src.cli.commands.db.runtime_compose.get_docker_compose_postgres_connection")
def test_compose_runtime_factory(mock_get_conn, mock_get_settings):
    """Test that get_compose_runtime returns a properly configured DbRuntime."""
    from src.cli.commands.db.runtime_compose import get_compose_runtime

    runtime = get_compose_runtime()

    assert runtime.name == "compose"
    assert runtime.console is not None
    assert callable(runtime.get_settings)
    assert callable(runtime.connect)
    assert callable(runtime.port_forward)
    assert callable(runtime.get_deployer)
    assert len(runtime.secrets_dirs) > 0
    assert callable(runtime.is_temporal_enabled)
    assert callable(runtime.is_bundled_postgres_enabled)


@patch("src.cli.commands.db.runtime_k8s.get_settings")
@patch("src.cli.commands.db.runtime_k8s.get_k8s_postgres_connection")
@patch("src.cli.commands.db.runtime_k8s.postgres_port_forward_if_needed")
def test_k8s_runtime_factory(mock_port_forward, mock_get_conn, mock_get_settings):
    """Test that get_k8s_runtime returns a properly configured DbRuntime."""
    from src.cli.commands.db.runtime_k8s import get_k8s_runtime

    runtime = get_k8s_runtime()

    assert runtime.name == "k8s"
    assert runtime.console is not None
    assert callable(runtime.get_settings)
    assert callable(runtime.connect)
    assert callable(runtime.port_forward)
    assert callable(runtime.get_deployer)
    assert len(runtime.secrets_dirs) > 0
    assert callable(runtime.is_temporal_enabled)
    assert callable(runtime.is_bundled_postgres_enabled)


def test_compose_runtime_port_forward_returns_nullcontext():
    """Test that compose runtime port_forward returns a no-op context."""
    from src.cli.commands.db.runtime_compose import get_compose_runtime

    runtime = get_compose_runtime()

    # Should return a context manager that does nothing
    with runtime.port_forward() as result:
        assert result is None


@patch("src.cli.commands.db.runtime_k8s.postgres_port_forward_if_needed")
@patch("src.cli.commands.db.runtime_k8s.get_namespace")
@patch("src.cli.commands.db.runtime_k8s.get_postgres_label")
def test_k8s_runtime_port_forward_uses_namespace_and_label(
    mock_get_label, mock_get_ns, mock_port_forward
):
    """Test that k8s runtime port_forward uses proper namespace and label."""
    from src.cli.commands.db.runtime_k8s import get_k8s_runtime

    mock_get_ns.return_value = "test-namespace"
    mock_get_label.return_value = "app=postgres"
    mock_port_forward.return_value = MagicMock()

    runtime = get_k8s_runtime()
    runtime.port_forward()

    # Verify port_forward was called with correct params
    mock_port_forward.assert_called_once_with(
        namespace="test-namespace", pod_label="app=postgres"
    )


def test_runtime_connect_callable_signature():
    """Test that runtime connect callable has expected signature."""
    from src.cli.commands.db.runtime_compose import get_compose_runtime

    runtime = get_compose_runtime()

    # Should accept settings and superuser_mode
    mock_settings = Mock()
    mock_settings.host = "localhost"

    # This will fail if signature is wrong
    with patch(
        "src.cli.commands.db.runtime_compose.get_docker_compose_postgres_connection"
    ) as mock_conn:
        mock_conn.return_value = Mock()
        runtime.connect(mock_settings, True)
        mock_conn.assert_called_once_with(mock_settings, superuser_mode=True)

        mock_conn.reset_mock()
        runtime.connect(mock_settings, False)
        mock_conn.assert_called_once_with(mock_settings, superuser_mode=False)


# =============================================================================
# Workflow Tests
# =============================================================================


@pytest.fixture
def mock_runtime():
    """Create a mock DbRuntime for testing workflows."""
    runtime = MagicMock(spec=DbRuntime)
    runtime.name = "test"
    runtime.console = Mock()
    runtime.get_settings = Mock()
    runtime.connect = MagicMock()
    runtime.port_forward = no_port_forward
    runtime.get_deployer = Mock()
    runtime.secrets_dirs = [Path("/fake/secrets")]
    runtime.is_temporal_enabled = Mock(return_value=False)
    runtime.is_bundled_postgres_enabled = Mock(return_value=False)
    return runtime


class TestRunInit:
    """Test run_init workflow."""

    @patch("src.infra.postgres.PostgresInitializer")
    def test_run_init_success(self, mock_initializer_class, mock_runtime):
        """Verify run_init() calls PostgresInitializer.initialize()."""
        from src.cli.commands.db import run_init

        # Setup mocks
        mock_settings = Mock()
        mock_settings.ensure_all_passwords.return_value = mock_settings
        mock_runtime.get_settings.return_value = mock_settings

        mock_conn = MagicMock()
        mock_runtime.connect.return_value.__enter__.return_value = mock_conn

        mock_initializer = Mock()
        mock_initializer.initialize.return_value = True
        mock_initializer_class.return_value = mock_initializer

        # Execute
        result = run_init(mock_runtime)

        # Verify
        assert result is True
        mock_runtime.get_settings.assert_called_once()
        mock_settings.ensure_all_passwords.assert_called_once()
        mock_runtime.connect.assert_called_once_with(mock_settings, True)
        mock_initializer_class.assert_called_once_with(connection=mock_conn)
        mock_initializer.initialize.assert_called_once()

    @patch("src.infra.postgres.PostgresInitializer")
    def test_run_init_failure(self, mock_initializer_class, mock_runtime):
        """Verify run_init() returns False when initialization fails."""
        from src.cli.commands.db import run_init

        mock_settings = Mock()
        mock_settings.ensure_all_passwords.return_value = mock_settings
        mock_runtime.get_settings.return_value = mock_settings

        mock_conn = MagicMock()
        mock_runtime.connect.return_value.__enter__.return_value = mock_conn

        mock_initializer = Mock()
        mock_initializer.initialize.return_value = False
        mock_initializer_class.return_value = mock_initializer

        result = run_init(mock_runtime)

        assert result is False


class TestRunVerify:
    """Test run_verify workflow."""

    @patch("src.infra.postgres.PostgresVerifier")
    def test_run_verify_with_superuser_mode(self, mock_verifier_class, mock_runtime):
        """Verify run_verify() uses superuser_mode parameter correctly."""
        from src.cli.commands.db import run_verify

        mock_settings = Mock()
        mock_settings.ensure_all_passwords.return_value = mock_settings
        mock_runtime.get_settings.return_value = mock_settings

        mock_conn = MagicMock()
        mock_runtime.connect.return_value.__enter__.return_value = mock_conn

        mock_verifier = Mock()
        mock_verifier.verify_all.return_value = True
        mock_verifier_class.return_value = mock_verifier

        result = run_verify(mock_runtime, superuser_mode=True)

        assert result is True
        mock_runtime.connect.assert_called_once_with(mock_settings, True)

    @patch("src.infra.postgres.PostgresVerifier")
    def test_run_verify_without_superuser_mode(self, mock_verifier_class, mock_runtime):
        """Verify run_verify() can run without superuser mode."""
        from src.cli.commands.db import run_verify

        mock_settings = Mock()
        mock_settings.ensure_all_passwords.return_value = mock_settings
        mock_runtime.get_settings.return_value = mock_settings

        mock_conn = MagicMock()
        mock_runtime.connect.return_value.__enter__.return_value = mock_conn

        mock_verifier = Mock()
        mock_verifier.verify_all.return_value = True
        mock_verifier_class.return_value = mock_verifier

        result = run_verify(mock_runtime, superuser_mode=False)

        assert result is True
        mock_runtime.connect.assert_called_once_with(mock_settings, False)


class TestRunBackup:
    """Test run_backup workflow."""

    @patch("src.infra.postgres.PostgresBackup")
    def test_run_backup_returns_tuple(self, mock_backup_class, mock_runtime):
        """Verify run_backup() returns (success, path) tuple."""
        from src.cli.commands.db import run_backup

        mock_settings = Mock()
        mock_runtime.get_settings.return_value = mock_settings

        mock_conn = MagicMock()
        mock_runtime.connect.return_value.__enter__.return_value = mock_conn

        mock_backup = Mock()
        mock_backup.create_backup.return_value = (True, "/path/to/backup.sql")
        mock_backup_class.return_value = mock_backup

        output_dir = Path("/tmp/backups")
        success, path = run_backup(
            mock_runtime, output_dir=output_dir, superuser_mode=False
        )

        assert success is True
        assert path == "/path/to/backup.sql"
        mock_backup_class.assert_called_once_with(
            connection=mock_conn, backup_dir=output_dir
        )


class TestRunReset:
    """Test run_reset workflow."""

    @patch("src.infra.postgres.PostgresReset")
    def test_run_reset_with_temporal(self, mock_reset_class, mock_runtime):
        """Verify run_reset() passes include_temporal parameter."""
        from src.cli.commands.db import run_reset

        mock_settings = Mock()
        mock_runtime.get_settings.return_value = mock_settings

        mock_conn = MagicMock()
        mock_runtime.connect.return_value.__enter__.return_value = mock_conn

        mock_reset = Mock()
        mock_reset.reset.return_value = True
        mock_reset_class.return_value = mock_reset

        result = run_reset(mock_runtime, include_temporal=True, superuser_mode=True)

        assert result is True
        mock_reset.reset.assert_called_once_with(include_temporal=True)


class TestRunSync:
    """Test run_sync workflow."""

    @patch("src.infra.postgres.PostgresPasswordSync")
    def test_run_sync_without_bundled_postgres(self, mock_sync_class, mock_runtime):
        """Verify run_sync() skips bundled sync when not enabled."""
        from src.cli.commands.db import run_sync

        mock_runtime.is_bundled_postgres_enabled.return_value = False

        mock_settings = Mock()
        mock_runtime.get_settings.return_value = mock_settings

        mock_conn = MagicMock()
        mock_runtime.connect.return_value.__enter__.return_value = mock_conn

        mock_sync = Mock()
        mock_sync.sync_user_roles_and_passwords.return_value = True
        mock_sync_class.return_value = mock_sync

        result = run_sync(mock_runtime)

        assert result is True
        # Should only call get_settings once (at start of function)
        assert mock_runtime.get_settings.call_count == 1

    @patch("src.infra.postgres.PostgresPasswordSync")
    def test_run_sync_with_bundled_postgres(self, mock_sync_class, mock_runtime):
        """Verify run_sync() handles bundled postgres sync."""
        from src.cli.commands.db import run_sync

        mock_runtime.is_bundled_postgres_enabled.return_value = True

        mock_settings = Mock()
        mock_runtime.get_settings.return_value = mock_settings

        mock_conn = MagicMock()
        mock_runtime.connect.return_value.__enter__.return_value = mock_conn

        mock_deployer = Mock()
        mock_runtime.get_deployer.return_value = mock_deployer

        mock_sync = Mock()
        mock_sync.sync_bundled_superuser_password.return_value = True
        mock_sync.sync_user_roles_and_passwords.return_value = True
        mock_sync_class.return_value = mock_sync

        result = run_sync(mock_runtime)

        assert result is True
        # Should only call get_settings once (at start of function)
        assert mock_runtime.get_settings.call_count == 1
