"""Tests for Fly.io database runtime."""

from contextlib import nullcontext
from unittest.mock import patch

from src.cli.commands.fly.db_runtime import get_fly_runtime


class TestFlyRuntimeFactory:
    """Tests for the get_fly_runtime factory function."""

    def test_runtime_name_is_fly(self) -> None:
        """Runtime should have name 'fly'."""
        runtime = get_fly_runtime()
        assert runtime.name == "fly"

    def test_runtime_with_cluster_id(self) -> None:
        """Runtime should be created with cluster_id."""
        runtime = get_fly_runtime("test-cluster")
        assert runtime.name == "fly"

    def test_port_forward_returns_context_manager(self) -> None:
        """port_forward() should return a context manager."""
        runtime = get_fly_runtime("test-cluster")
        cm = runtime.port_forward()
        # Should be a context manager (has __enter__ and __exit__)
        assert hasattr(cm, "__enter__")
        assert hasattr(cm, "__exit__")

    def test_port_forward_without_cluster_id_returns_nullcontext(self) -> None:
        """port_forward() without cluster_id should do nothing."""
        runtime = get_fly_runtime(None)
        cm = runtime.port_forward()

        # The context manager should yield without doing anything
        # We can test by checking it doesn't raise
        with cm:
            pass

    @patch("src.cli.commands.fly.db_runtime.fly_postgres_port_forward_if_needed")
    def test_port_forward_calls_fly_port_forward(
        self,
        mock_port_forward,
    ) -> None:
        """port_forward() should use fly_postgres_port_forward_if_needed."""
        mock_port_forward.return_value = nullcontext()

        runtime = get_fly_runtime("my-cluster")
        runtime.port_forward()

        # Verify the function was called with correct cluster_id
        mock_port_forward.assert_called_once()
        call_kwargs = mock_port_forward.call_args[1]
        assert call_kwargs["cluster_id"] == "my-cluster"

    def test_temporal_is_disabled_for_fly(self) -> None:
        """Temporal should be disabled for Fly.io deployments."""
        runtime = get_fly_runtime()
        assert runtime.is_temporal_enabled() is False

    def test_bundled_postgres_is_disabled_for_fly(self) -> None:
        """Bundled postgres should be disabled for Fly.io (uses Fly Postgres)."""
        runtime = get_fly_runtime()
        assert runtime.is_bundled_postgres_enabled() is False

    def test_get_deployer_returns_none_for_fly(self) -> None:
        """get_deployer() should return None (no Helm for Fly.io)."""
        runtime = get_fly_runtime()
        assert runtime.get_deployer() is None
