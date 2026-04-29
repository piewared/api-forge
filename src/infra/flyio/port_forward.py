"""Fly.io PostgreSQL port forwarding context manager.

Provides automatic port forwarding to Fly Postgres clusters via flyctl proxy
for CLI operations. Uses the shared PortForwardRegistry for lifecycle management.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar

from rich.progress import Console

from src.infra.flyio.constants import FlyConstants
from src.infra.port_forward import (
    PortForwardError,
    PortForwardRegistry,
    wait_for_port_ready,
)

if TYPE_CHECKING:
    from src.infra.flyio.controller import FlyCtlControllerSync

# Type variable for function return type
T = TypeVar("T")

# Module-level registry instance
_registry = PortForwardRegistry()


class FlyPortForwardError(PortForwardError):
    """Error during Fly.io port forwarding setup."""


@dataclass
class FlyPortForwardKey:
    """Key for tracking active Fly.io port forwards."""

    cluster_id: str
    local_port: int

    def __hash__(self) -> int:
        return hash((self.cluster_id, self.local_port))


# Machine states that mean "not currently running and needs to be started
# before flyctl operations (proxy, deploy) will see a healthy peer".
_NOT_RUNNING_STATES = frozenset({"suspended", "stopped", "stopping"})


def ensure_app_machines_running(
    app_name: str,
    *,
    start_timeout: float = 60.0,
    poll_interval: float = 2.0,
    console: Any = None,
    controller: FlyCtlControllerSync | None = None,
) -> None:
    """Start any suspended or stopped machines for a Fly app.

    Fly machines do NOT auto-wake when a proxy connection or deploy is
    attempted — the operation simply hangs or fails with "no started VMs".
    This function explicitly starts any suspended/stopped machines and waits
    until they reach the 'started' state.

    All flyctl interaction goes through ``FlyCtlControllerSync`` (rather than
    direct ``subprocess.run`` calls) so testing, error handling, and command
    construction stay consistent with the rest of the Fly.io infra layer.

    Args:
        app_name:       The Fly app name.
        start_timeout:  Seconds to wait for machines to reach 'started' state.
        poll_interval:  Seconds between polls of machine state.
        console:        Optional object with a .print() method for status output.
        controller:     Existing FlyCtlControllerSync to reuse. When ``None``
                        (the default), a fresh one is constructed — convenient
                        for callers that don't already have one in scope, but
                        passing an existing controller avoids reconstructing
                        the underlying flyctl client.
    """
    # Local import — module-level would create a circular import via
    # src.infra.flyio.__init__.
    if controller is None:
        from src.infra.flyio.controller import FlyCtlControllerSync

        controller = FlyCtlControllerSync()

    machines = controller.machines_list(app_name)
    if not machines:
        return

    suspended = [m for m in machines if m.get("state") in _NOT_RUNNING_STATES]
    if not suspended:
        return

    if console:
        console.print(
            f"[dim]Waking {len(suspended)} suspended machine(s) for '{app_name}'...[/dim]"
        )

    for machine in suspended:
        machine_id = machine.get("id", "")
        if machine_id:
            controller.machine_start(app_name, machine_id)

    # Poll until all previously-suspended machines reach 'started'.
    pending_ids = {m["id"] for m in suspended if m.get("id")}
    deadline = time.time() + start_timeout
    while time.time() < deadline and pending_ids:
        time.sleep(poll_interval)
        current = controller.machines_list(app_name)
        if not current:
            # Controller returns [] both for "no machines" and for transient
            # flyctl errors; either way we can't tell more, so stop polling.
            break
        started_now = {
            m["id"]
            for m in current
            if m.get("id") in pending_ids and m.get("state") == "started"
        }
        pending_ids -= started_now

    if pending_ids and console:
        console.print(
            f"[yellow]Warning: {len(pending_ids)} machine(s) may not be "
            "fully started yet[/yellow]"
        )


def _build_proxy_command(
    cluster_id: str, local_port: int, *, legacy: bool
) -> tuple[list[str], str]:
    """Build the flyctl proxy command.

    Returns:
        Tuple of (command args, proxy type label)
    """
    if legacy:
        return (
            ["fly", "proxy", f"{local_port}:5432", "-a", cluster_id],
            "legacy",
        )
    return (
        ["fly", "mpg", "proxy", cluster_id, "--port", str(local_port)],
        "managed",
    )


@contextmanager
def fly_postgres_port_forward(
    cluster_id: str,
    console: Console | None = None,
    *,
    local_port: int = FlyConstants.PROXY_LOCAL_PORT,
    timeout: float = FlyConstants.PROXY_STARTUP_TIMEOUT,
    reuse_existing: bool = True,
    legacy: bool = False,
) -> Generator[None]:
    """Context manager for Fly Postgres port forwarding.

    Automatically sets up and tears down flyctl proxy for PostgreSQL access.
    Uses reference counting to allow nested/concurrent calls to reuse the same
    proxy process.

    Args:
        cluster_id: Fly Managed Postgres cluster ID or name (or legacy app name)
        console: Rich console for output
        local_port: Local port to forward to (default: 54321)
        timeout: Seconds to wait for proxy to start
        reuse_existing: If True, reuse existing forward if available (default: True)
        legacy: If True, use legacy `fly proxy` command instead of `fly mpg proxy`

    Yields:
        None - port forwarding is active during context

    Raises:
        FlyPortForwardError: If port forwarding fails to start or port is in use
    """
    key = FlyPortForwardKey(cluster_id=cluster_id, local_port=local_port)

    def start_fn() -> subprocess.Popen[str]:
        if legacy:
            ensure_app_machines_running(cluster_id, console=console)

        cmd, proxy_type = _build_proxy_command(cluster_id, local_port, legacy=legacy)

        if console:
            console.print(
                f"[dim]Starting Fly proxy ({proxy_type}) to: {cluster_id} on port {local_port}[/dim]"
            )

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if not wait_for_port_ready(local_port, timeout=timeout):
            if process.poll() is not None:
                _, stderr = process.communicate()
                raise FlyPortForwardError(
                    f"Fly proxy failed to start: {stderr.strip()}"
                )
            else:
                process.terminate()
                raise FlyPortForwardError(
                    f"Fly proxy did not become ready within {timeout}s"
                )

        if console:
            console.print(
                f"[dim]Fly proxy active: localhost:{local_port} -> {cluster_id}[/dim]"
            )

        return process

    with _registry.forward(
        key,
        local_port=local_port,
        start_fn=start_fn,
        reuse_existing=reuse_existing,
        console=console,
    ):
        yield


@contextmanager
def fly_postgres_port_forward_if_needed(
    cluster_id: str | None,
    console: Console | None = None,
    *,
    local_port: int = FlyConstants.PROXY_LOCAL_PORT,
    timeout: float = FlyConstants.PROXY_STARTUP_TIMEOUT,
    reuse_existing: bool = True,
    legacy: bool = False,
) -> Generator[None]:
    """Context manager that sets up Fly port forwarding only if a cluster_id is provided.

    When cluster_id is None, assumes direct connection within the Fly.io network.

    Args:
        cluster_id: Fly Managed Postgres cluster ID or name (None for direct connection)
        console: Rich console for output
        local_port: Local port to forward to (default: 54321)
        timeout: Seconds to wait for proxy to start
        reuse_existing: If True, reuse existing forward if available (default: True)
        legacy: If True, use legacy `fly proxy` command instead of `fly mpg proxy`

    Yields:
        None
    """
    if cluster_id is None:
        yield
        return

    with fly_postgres_port_forward(
        cluster_id=cluster_id,
        console=console,
        local_port=local_port,
        timeout=timeout,
        reuse_existing=reuse_existing,
        legacy=legacy,
    ):
        yield


def with_fly_postgres_port_forward(
    cluster_id: str | None = None,
    *,
    local_port: int = FlyConstants.PROXY_LOCAL_PORT,
    timeout: float = FlyConstants.PROXY_STARTUP_TIMEOUT,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to automatically set up Fly port forwarding for a function.

    Args:
        cluster_id: Cluster ID or name (if None, tries to get from function kwargs)
        local_port: Local port to forward to (default: 54321)
        timeout: Seconds to wait for proxy to start

    Returns:
        Decorator function
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            actual_cluster_id = cluster_id
            if actual_cluster_id is None:
                actual_cluster_id = kwargs.get("cluster_id") or kwargs.get("cluster")

            with fly_postgres_port_forward_if_needed(
                cluster_id=actual_cluster_id,
                local_port=local_port,
                timeout=timeout,
            ):
                return func(*args, **kwargs)

        return wrapper

    return decorator
