"""Tests for the k8s database runtime adapter.

Lives in ``tests/unit/cli/commands/k8s/`` so the whole file is excluded by
``copier.yml`` when ``include_k8s_deploy=false`` — the imports below would
fail at collection time in a generated project without the k8s subtree.
"""

from unittest.mock import MagicMock, patch


@patch("src.cli.commands.k8s.db_runtime.get_db_settings")
@patch("src.cli.commands.k8s.db_runtime.get_k8s_postgres_connection")
@patch("src.cli.commands.k8s.db_runtime.postgres_port_forward_if_needed")
def test_k8s_runtime_factory(mock_port_forward, mock_get_conn, mock_get_settings):
    """Test that get_k8s_runtime returns a properly configured DbRuntime."""
    from src.cli.commands.k8s.db_runtime import get_k8s_runtime

    runtime = get_k8s_runtime()

    assert runtime.name == "k8s"
    assert runtime.console is not None
    assert callable(runtime.get_settings)
    assert callable(runtime.connect)
    assert callable(runtime.port_forward)
    assert callable(runtime.get_deployer)
    assert runtime.secrets_manager is not None
    assert callable(runtime.is_temporal_enabled)
    assert callable(runtime.is_bundled_postgres_enabled)


@patch("src.cli.commands.k8s.db_runtime.postgres_port_forward_if_needed")
@patch("src.cli.commands.k8s.db_runtime.get_namespace")
@patch("src.cli.commands.k8s.db_runtime.get_postgres_label")
def test_k8s_runtime_port_forward_uses_namespace_and_label(
    mock_get_label, mock_get_ns, mock_port_forward
):
    """Test that k8s runtime port_forward uses proper namespace and label."""
    from src.cli.commands.k8s.db_runtime import get_k8s_runtime

    mock_get_ns.return_value = "test-namespace"
    mock_get_label.return_value = "app=postgres"
    mock_port_forward.return_value = MagicMock()

    runtime = get_k8s_runtime()
    runtime.port_forward()

    mock_port_forward.assert_called_once_with(
        namespace="test-namespace", pod_label="app=postgres"
    )
