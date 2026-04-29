"""Tests for the shared PortForwardRegistry."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.infra.port_forward import PortForwardError, PortForwardRegistry


class TestPortForwardRegistry:
    """Tests for PortForwardRegistry lifecycle management."""

    def _make_process(self, *, alive: bool = True) -> MagicMock:
        """Create a mock subprocess."""
        proc = MagicMock(spec=subprocess.Popen)
        proc.poll.return_value = None if alive else 0
        return proc

    @patch("src.infra.port_forward.registry.is_port_in_use", return_value=False)
    def test_forward_starts_and_stops_process(self, _: MagicMock) -> None:
        """Should start process on enter and terminate on exit."""
        registry = PortForwardRegistry()
        proc = self._make_process()

        with registry.forward("key-1", local_port=5432, start_fn=lambda: proc):
            assert registry._active["key-1"].ref_count == 1

        proc.terminate.assert_called_once()
        assert "key-1" not in registry._active

    @patch("src.infra.port_forward.registry.is_port_in_use", return_value=False)
    def test_ref_counting_reuses_forward(self, _: MagicMock) -> None:
        """Nested forwards should reuse the same process via ref counting."""
        registry = PortForwardRegistry()
        proc = self._make_process()
        call_count = 0

        def start_fn() -> MagicMock:
            nonlocal call_count
            call_count += 1
            return proc

        with registry.forward("key-1", local_port=5432, start_fn=start_fn):
            assert registry._active["key-1"].ref_count == 1
            with registry.forward("key-1", local_port=5432, start_fn=start_fn):
                assert registry._active["key-1"].ref_count == 2
            # Inner exited, ref count decremented but process still alive
            assert registry._active["key-1"].ref_count == 1
            proc.terminate.assert_not_called()

        # Outer exited, process terminated
        proc.terminate.assert_called_once()
        assert call_count == 1  # start_fn only called once

    @patch("src.infra.port_forward.registry.is_port_in_use", return_value=True)
    def test_raises_when_port_in_use(self, _: MagicMock) -> None:
        """Should raise PortForwardError when port is already in use."""
        registry = PortForwardRegistry()

        with pytest.raises(PortForwardError, match="already in use"):
            with registry.forward(
                "key-1", local_port=5432, start_fn=lambda: self._make_process()
            ):
                pass

    @patch("src.infra.port_forward.registry.is_port_in_use", return_value=False)
    def test_dead_process_gets_replaced(self, _: MagicMock) -> None:
        """Should replace a dead process when reuse is attempted."""
        registry = PortForwardRegistry()
        dead_proc = self._make_process(alive=False)
        new_proc = self._make_process()

        # Manually insert a dead process
        from src.infra.port_forward.types import PortForwardProcess

        registry._active["key-1"] = PortForwardProcess(process=dead_proc)

        with registry.forward("key-1", local_port=5432, start_fn=lambda: new_proc):
            assert registry._active["key-1"].process is new_proc

    def test_cleanup_stale_removes_dead_processes(self) -> None:
        """cleanup_stale should remove entries with dead processes."""
        registry = PortForwardRegistry()
        from src.infra.port_forward.types import PortForwardProcess

        alive = self._make_process(alive=True)
        dead = self._make_process(alive=False)

        registry._active["alive"] = PortForwardProcess(process=alive)
        registry._active["dead"] = PortForwardProcess(process=dead)

        registry.cleanup_stale()

        assert "alive" in registry._active
        assert "dead" not in registry._active

    @patch("src.infra.port_forward.registry.is_port_in_use", return_value=False)
    def test_force_kill_on_terminate_timeout(self, _: MagicMock) -> None:
        """Should force kill if terminate doesn't work within timeout."""
        registry = PortForwardRegistry()
        proc = self._make_process()
        proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), None]

        with registry.forward("key-1", local_port=5432, start_fn=lambda: proc):
            pass

        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
