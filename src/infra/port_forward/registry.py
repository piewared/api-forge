"""Port forward registry with reference counting and lifecycle management.

Provides a reusable registry that tracks active port-forward processes,
handles stale cleanup, port-in-use detection, and ref-counted context managers.
Used by both Fly.io and Kubernetes port forwarding.
"""

import socket
import subprocess
import time
from collections.abc import Generator, Hashable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from .types import PortForwardError, PortForwardProcess


def is_port_in_use(port: int, host: str = "localhost") -> bool:
    """Check if a local port is already in use.

    Args:
        port: Port number to check
        host: Host to check on (default: localhost)

    Returns:
        True if port is in use, False otherwise
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return False
        except OSError:
            return True


def wait_for_port_ready(
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 30.0,
    check_interval: float = 0.5,
) -> bool:
    """Wait for a port to become ready (accepting connections).

    Args:
        port: Port number to check
        host: Host to check on
        timeout: Maximum time to wait in seconds
        check_interval: Time between checks in seconds

    Returns:
        True if port became ready, False if timeout
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return True
        except OSError:
            pass
        time.sleep(check_interval)
    return False


@dataclass
class PortForwardRegistry:
    """Registry of active port-forward processes with ref counting.

    Manages the lifecycle of port-forward subprocesses:
    - Tracks active forwards by hashable key
    - Reuses existing forwards via reference counting
    - Cleans up stale (dead) processes
    - Terminates processes when last reference is released

    Example:
        registry = PortForwardRegistry()
        with registry.forward(key, local_port=5432, start_fn=my_start):
            # port forward is active
            pass
        # automatically cleaned up when last ref exits
    """

    _active: dict[Hashable, PortForwardProcess] = field(
        default_factory=dict, init=False
    )

    def cleanup_stale(self) -> None:
        """Remove any dead port-forward processes from the registry."""
        stale_keys = [
            key for key, fwd in self._active.items() if fwd.process.poll() is not None
        ]
        for key in stale_keys:
            del self._active[key]

    @contextmanager
    def forward(
        self,
        key: Hashable,
        *,
        local_port: int,
        start_fn: Any,
        reuse_existing: bool = True,
        console: Any = None,
    ) -> Generator[None]:
        """Context manager that manages a port-forward process with ref counting.

        Args:
            key: Hashable key identifying this forward (must be unique per config)
            local_port: Local port being forwarded (for port-in-use checks)
            start_fn: Callable that starts the port-forward subprocess.
                       Must return a subprocess.Popen[str].
                       Receives no arguments — caller should use a closure/lambda.
            reuse_existing: If True, reuse existing forward if available
            console: Optional object with .print() for status messages

        Yields:
            None — port forwarding is active during context

        Raises:
            PortForwardError: If port is already in use and no existing forward found
        """
        forward = self._acquire(key, local_port, start_fn, reuse_existing, console)
        try:
            yield
        finally:
            self._release(key, forward, console)

    def _acquire(
        self,
        key: Hashable,
        local_port: int,
        start_fn: Any,
        reuse_existing: bool,
        console: Any,
    ) -> PortForwardProcess:
        """Acquire a port-forward reference, starting a new process if needed."""
        # Check for existing forward
        forward: PortForwardProcess | None = None
        if reuse_existing and key in self._active:
            forward = self._active[key]
            if forward.process.poll() is not None:
                del self._active[key]
                forward = None

        if forward is None:
            forward = self._start_new(key, local_port, start_fn, console)

        forward.ref_count += 1
        return forward

    def _start_new(
        self,
        key: Hashable,
        local_port: int,
        start_fn: Any,
        console: Any,
    ) -> PortForwardProcess:
        """Start a new port-forward process after checking port availability."""
        if is_port_in_use(local_port):
            self.cleanup_stale()
            if is_port_in_use(local_port):
                raise PortForwardError(
                    f"Port {local_port} is already in use and no existing forward found."
                )

        process = start_fn()
        forward = PortForwardProcess(process=process)
        self._active[key] = forward
        return forward

    def _release(
        self,
        key: Hashable,
        forward: PortForwardProcess,
        console: Any,
    ) -> None:
        """Release a port-forward reference, terminating if last."""
        forward.ref_count -= 1

        if console:
            console.print(
                f"[dim]Released port-forward reference (refs={forward.ref_count})[/dim]"
            )

        if forward.ref_count > 0:
            return

        if forward.process.poll() is None:
            if console:
                console.print("[dim]Stopping port-forward...[/dim]")
            forward.process.terminate()
            try:
                forward.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                forward.process.kill()
                forward.process.wait()

        if key in self._active and self._active[key] is forward:
            del self._active[key]

        if console:
            console.print("[dim]Port-forward stopped[/dim]")
