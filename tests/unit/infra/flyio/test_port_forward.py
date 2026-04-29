"""Tests for Fly.io port forwarding utilities."""

from unittest.mock import MagicMock, patch

import pytest

from src.infra.flyio.port_forward import (
    FlyPortForwardError,
    FlyPortForwardKey,
    ensure_app_machines_running,
    fly_postgres_port_forward,
    fly_postgres_port_forward_if_needed,
    with_fly_postgres_port_forward,
)
from src.infra.port_forward import PortForwardError, is_port_in_use, wait_for_port_ready


class TestFlyPortForwardKey:
    """Tests for FlyPortForwardKey dataclass."""

    def test_key_equality(self) -> None:
        """Keys with same values should be equal."""
        key1 = FlyPortForwardKey(cluster_id="test-cluster", local_port=54321)
        key2 = FlyPortForwardKey(cluster_id="test-cluster", local_port=54321)
        assert key1 == key2

    def test_key_hash(self) -> None:
        """Keys with same values should have same hash."""
        key1 = FlyPortForwardKey(cluster_id="test-cluster", local_port=54321)
        key2 = FlyPortForwardKey(cluster_id="test-cluster", local_port=54321)
        assert hash(key1) == hash(key2)

    def test_different_cluster_different_key(self) -> None:
        """Keys with different clusters should not be equal."""
        key1 = FlyPortForwardKey(cluster_id="cluster-1", local_port=54321)
        key2 = FlyPortForwardKey(cluster_id="cluster-2", local_port=54321)
        assert key1 != key2


class TestPortUtilities:
    """Tests for shared port-related utility functions."""

    def test_is_port_in_use_free_port(self) -> None:
        """Should return False for unused ports."""
        with patch("src.infra.port_forward.registry.socket.socket") as mock_socket:
            mock_sock_instance = MagicMock()
            mock_socket.return_value.__enter__.return_value = mock_sock_instance
            mock_sock_instance.bind.return_value = None

            result = is_port_in_use(59999)
            assert result is False

    def test_is_port_in_use_used_port(self) -> None:
        """Should return True for used ports."""
        with patch("src.infra.port_forward.registry.socket.socket") as mock_socket:
            mock_sock_instance = MagicMock()
            mock_socket.return_value.__enter__.return_value = mock_sock_instance
            mock_sock_instance.bind.side_effect = OSError("Address in use")

            result = is_port_in_use(59999)
            assert result is True

    def test_wait_for_port_ready_success(self) -> None:
        """Should return True when port becomes ready."""
        with patch("src.infra.port_forward.registry.socket.socket") as mock_socket:
            mock_sock_instance = MagicMock()
            mock_socket.return_value = mock_sock_instance
            mock_sock_instance.connect_ex.return_value = 0

            result = wait_for_port_ready(54321, timeout=1.0)
            assert result is True

    def test_wait_for_port_ready_timeout(self) -> None:
        """Should return False when port never becomes ready."""
        with patch("src.infra.port_forward.registry.socket.socket") as mock_socket:
            mock_sock_instance = MagicMock()
            mock_socket.return_value = mock_sock_instance
            mock_sock_instance.connect_ex.return_value = 111

            result = wait_for_port_ready(54321, timeout=0.1, check_interval=0.05)
            assert result is False


class TestFlyPostgresPortForward:
    """Tests for the fly_postgres_port_forward context manager."""

    @patch("src.infra.flyio.port_forward.subprocess.Popen")
    @patch("src.infra.flyio.port_forward.wait_for_port_ready")
    @patch("src.infra.port_forward.registry.is_port_in_use")
    def test_port_forward_starts_proxy(
        self,
        mock_is_port_in_use: MagicMock,
        mock_wait_ready: MagicMock,
        mock_popen: MagicMock,
    ) -> None:
        """Should start flyctl proxy when entering context."""
        mock_is_port_in_use.return_value = False
        mock_wait_ready.return_value = True

        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        with fly_postgres_port_forward("test-cluster", local_port=54321):
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args
            cmd = call_args[0][0]
            assert cmd == ["fly", "mpg", "proxy", "test-cluster", "--port", "54321"]

        mock_process.terminate.assert_called_once()

    @patch("src.infra.port_forward.registry.is_port_in_use")
    def test_port_forward_raises_when_port_in_use(
        self,
        mock_is_port_in_use: MagicMock,
    ) -> None:
        """Should raise error when port is already in use."""
        mock_is_port_in_use.return_value = True

        with pytest.raises(PortForwardError, match="already in use"):
            with fly_postgres_port_forward("test-cluster", local_port=54321):
                pass

    @patch("src.infra.flyio.port_forward.subprocess.Popen")
    @patch("src.infra.flyio.port_forward.wait_for_port_ready")
    @patch("src.infra.port_forward.registry.is_port_in_use")
    def test_port_forward_raises_on_timeout(
        self,
        mock_is_port_in_use: MagicMock,
        mock_wait_ready: MagicMock,
        mock_popen: MagicMock,
    ) -> None:
        """Should raise error when proxy doesn't start in time."""
        mock_is_port_in_use.return_value = False
        mock_wait_ready.return_value = False

        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        with pytest.raises(FlyPortForwardError, match="did not become ready"):
            with fly_postgres_port_forward(
                "test-cluster", local_port=54321, timeout=0.1
            ):
                pass


class TestFlyPostgresPortForwardIfNeeded:
    """Tests for the fly_postgres_port_forward_if_needed context manager."""

    def test_no_forward_when_cluster_id_none(self) -> None:
        """Should not start proxy when cluster_id is None."""
        with patch(
            "src.infra.flyio.port_forward.fly_postgres_port_forward"
        ) as mock_forward:
            with fly_postgres_port_forward_if_needed(None):
                pass

            mock_forward.assert_not_called()

    @patch("src.infra.flyio.port_forward.fly_postgres_port_forward")
    def test_forward_when_cluster_id_provided(
        self,
        mock_forward: MagicMock,
    ) -> None:
        """Should start proxy when cluster_id is provided."""
        mock_forward.return_value.__enter__ = MagicMock()
        mock_forward.return_value.__exit__ = MagicMock(return_value=False)

        with fly_postgres_port_forward_if_needed("test-cluster"):
            pass

        mock_forward.assert_called_once()
        call_kwargs = mock_forward.call_args[1]
        assert call_kwargs["cluster_id"] == "test-cluster"


class TestWithFlyPostgresPortForward:
    """Tests for the with_fly_postgres_port_forward decorator."""

    @patch("src.infra.flyio.port_forward.fly_postgres_port_forward_if_needed")
    def test_decorator_uses_provided_cluster_id(
        self,
        mock_forward: MagicMock,
    ) -> None:
        """Should use cluster_id provided to decorator."""
        mock_forward.return_value.__enter__ = MagicMock()
        mock_forward.return_value.__exit__ = MagicMock(return_value=False)

        @with_fly_postgres_port_forward(cluster_id="my-cluster")
        def my_func() -> str:
            return "result"

        result = my_func()
        assert result == "result"

        mock_forward.assert_called_once()
        call_kwargs = mock_forward.call_args[1]
        assert call_kwargs["cluster_id"] == "my-cluster"

    @patch("src.infra.flyio.port_forward.fly_postgres_port_forward_if_needed")
    def test_decorator_extracts_cluster_id_from_kwargs(
        self,
        mock_forward: MagicMock,
    ) -> None:
        """Should extract cluster_id from function kwargs."""
        mock_forward.return_value.__enter__ = MagicMock()
        mock_forward.return_value.__exit__ = MagicMock(return_value=False)

        @with_fly_postgres_port_forward()
        def my_func(cluster_id: str) -> str:
            return f"connected to {cluster_id}"

        result = my_func(cluster_id="dynamic-cluster")
        assert result == "connected to dynamic-cluster"

        mock_forward.assert_called_once()
        call_kwargs = mock_forward.call_args[1]
        assert call_kwargs["cluster_id"] == "dynamic-cluster"


# ---------- ensure_app_machines_running ----------


class TestEnsureAppMachinesRunning:
    """``ensure_app_machines_running`` must drive flyctl through the
    FlyCtlControllerSync abstraction, not direct subprocess.run calls."""

    def test_no_machines_short_circuits(self) -> None:
        controller = MagicMock()
        controller.machines_list.return_value = []

        ensure_app_machines_running("my-app", controller=controller)

        controller.machines_list.assert_called_once_with("my-app")
        controller.machine_start.assert_not_called()

    def test_all_running_does_not_start_anything(self) -> None:
        controller = MagicMock()
        controller.machines_list.return_value = [
            {"id": "m1", "state": "started"},
            {"id": "m2", "state": "started"},
        ]

        ensure_app_machines_running("my-app", controller=controller)

        controller.machine_start.assert_not_called()

    def test_starts_suspended_machines_via_controller(self) -> None:
        """The first machines_list returns 'suspended' machines; the second
        (poll) shows them 'started', so the loop exits without further
        machine_start calls. machine_start must be invoked through the
        controller — never via subprocess."""
        controller = MagicMock()
        controller.machines_list.side_effect = [
            [
                {"id": "m1", "state": "suspended"},
                {"id": "m2", "state": "started"},
                {"id": "m3", "state": "stopped"},
            ],
            [
                {"id": "m1", "state": "started"},
                {"id": "m2", "state": "started"},
                {"id": "m3", "state": "started"},
            ],
        ]

        ensure_app_machines_running(
            "my-app",
            controller=controller,
            poll_interval=0.0,  # don't actually sleep in tests
        )

        # m1 (suspended) and m3 (stopped) get started; m2 was already running.
        assert controller.machine_start.call_count == 2
        controller.machine_start.assert_any_call("my-app", "m1")
        controller.machine_start.assert_any_call("my-app", "m3")

    def test_pending_machines_warned_when_timeout_expires(self) -> None:
        """If a machine never reaches 'started', the function should warn
        rather than hang forever."""
        controller = MagicMock()
        # Suspended on every call — never starts.
        controller.machines_list.return_value = [
            {"id": "m1", "state": "suspended"},
        ]
        console = MagicMock()

        ensure_app_machines_running(
            "my-app",
            controller=controller,
            console=console,
            start_timeout=0.05,
            poll_interval=0.0,
        )

        # The warning text must mention machines that didn't start.
        warned = any(
            "may not be fully started" in str(call)
            for call in console.print.call_args_list
        )
        assert warned, console.print.call_args_list
