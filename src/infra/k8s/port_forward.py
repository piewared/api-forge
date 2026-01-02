"""PostgreSQL port forwarding context manager for Kubernetes.

Provides automatic port forwarding to PostgreSQL pods in Kubernetes
for CLI operations.
"""

import socket
import subprocess
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache, wraps
from typing import Any, TypeVar

from rich.progress import Console

from src.infra.constants import DEFAULT_CONSTANTS
from src.infra.k8s.helpers import (
    get_k8s_controller,
    get_namespace,
    get_postgres_label,
)
from src.infra.k8s.utils import run_sync
from src.infra.utils.service_config import is_bundled_postgres_enabled

CONTROLLER = get_k8s_controller()

# Type variable for function return type
T = TypeVar("T")


class PortForwardError(Exception):
    """Error during port forwarding setup."""


@dataclass
class PortForwardKey:
    """Key for tracking active port forwards."""

    namespace: str
    pod_name: str
    local_port: int
    remote_port: int

    def __hash__(self) -> int:
        return hash((self.namespace, self.pod_name, self.local_port, self.remote_port))


@dataclass
class PortForwardProcess:
    """Tracks an active port forward process."""

    process: subprocess.Popen[str]
    ref_count: int = 1


# Global registry of active port forwards
_active_forwards: dict[PortForwardKey, PortForwardProcess] = {}


def _cleanup_stale_forwards() -> None:
    """Remove any dead port-forward processes from the registry.

    This handles cases where the port-forward process died unexpectedly
    (e.g., pod restart) but wasn't properly cleaned up.
    """
    stale_keys = []
    for key, forward in _active_forwards.items():
        if forward.process.poll() is not None:
            # Process has terminated
            stale_keys.append(key)

    for key in stale_keys:
        del _active_forwards[key]


def _is_port_in_use(port: int, host: str = "localhost") -> bool:
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


@lru_cache(maxsize=1)
def _get_postgres_pod() -> str | None:
    """Get the name of the PostgreSQL pod."""
    p_pods = run_sync(
        CONTROLLER.get_pods(get_namespace(), label_selector=get_postgres_label())
    )
    if p_pods:
        # Type narrowing: if list is non-empty, first element exists
        pod = p_pods[0]
        return pod.name

    return None


@contextmanager
def postgres_port_forward(
    namespace: str,
    console: Console | None = None,
    *,
    pod_name: str | None = None,
    pod_label: str | None = None,
    local_port: int = DEFAULT_CONSTANTS.DEFAULT_EPHEMERAL_PORT,
    remote_port: int = 5432,
    wait_time: float = 2.0,
    reuse_existing: bool = True,
) -> Generator[None]:
    """Context manager for PostgreSQL port forwarding.

    Automatically sets up and tears down kubectl port-forward for PostgreSQL access.
    Uses reference counting to allow nested/concurrent calls to reuse the same
    port-forward process.

    Args:
        namespace: Kubernetes namespace containing the pod
        console: Rich console for output
        pod_name: Name of the PostgreSQL pod
        pod_label: Label selector to find pod (if pod_name not provided)
        local_port: Local port to forward to (default: 5432)
        remote_port: Remote port on the pod (default: 5432)
        wait_time: Time to wait for port-forward to be ready (default: 2.0s)
        reuse_existing: If True, reuse existing forward if available (default: True)

    Yields:
        None - port forwarding is active during context

    Raises:
        PortForwardError: If port forwarding fails to start or port is in use

    Example:
        >>> with postgres_port_forward("api-forge-prod", pod_name="postgres-0"):
        ...     # Port 5432 is now forwarded to postgres-0:5432
        ...     conn = psycopg2.connect(host="localhost", port=5432, ...)
        ...     # Do database operations
        ... # Port forwarding automatically stopped (when last reference exits)

        >>> # Nested calls reuse the same forward:
        >>> with postgres_port_forward("api-forge-prod", pod_name="postgres-0"):
        ...     # First forward starts
        ...     with postgres_port_forward("api-forge-prod", pod_name="postgres-0"):
        ...         # Reuses existing forward (ref_count=2)
        ...         pass
        ...     # ref_count=1, forward still active
        ... # ref_count=0, forward stopped
    """
    if not pod_name:
        if not pod_label:
            raise PortForwardError("Either pod_name or pod_label must be provided")
        pod_name = _get_postgres_pod()
        if not pod_name:
            raise PortForwardError(
                f"No pod found with label '{pod_label}' in namespace '{namespace}'"
            )

    # Create key for this forward
    key = PortForwardKey(
        namespace=namespace,
        pod_name=pod_name,
        local_port=local_port,
        remote_port=remote_port,
    )

    # Check if we already have an active forward for this config
    forward: PortForwardProcess | None = None
    if reuse_existing and key in _active_forwards:
        forward = _active_forwards[key]
        # Verify process is still alive
        if forward.process.poll() is not None:
            # Process died, remove stale entry and create new
            del _active_forwards[key]
            forward = None

    # Create new forward if needed
    if forward is None:
        # Check if port is already in use by something else
        if _is_port_in_use(local_port):
            # Before failing, cleanup any stale entries that might be lingering
            _cleanup_stale_forwards()
            # Check again after cleanup
            if _is_port_in_use(local_port):
                raise PortForwardError(
                    f"Port {local_port} is already in use and no existing forward found."
                )

        cmd = [
            "kubectl",
            "port-forward",
            "-n",
            namespace,
            pod_name,
            f"{local_port}:{remote_port}",
        ]

        if console:
            console.print(
                f"[dim]Starting port-forward: {pod_name} {local_port}:{remote_port}[/dim]"
            )

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Wait for port-forward to be ready
        time.sleep(wait_time)

        # Check if process started successfully
        if process.poll() is not None:
            _, stderr = process.communicate()
            raise PortForwardError(f"Port forward failed to start: {stderr.strip()}")

        forward = PortForwardProcess(process=process, ref_count=0)
        _active_forwards[key] = forward

        if console:
            console.print(
                f"[dim]Port-forward active: localhost:{local_port} -> {pod_name}:{remote_port}[/dim]"
            )
    else:
        if console:
            console.print(
                f"[dim]Reusing existing port-forward: {pod_name} "
                f"{local_port}:{remote_port}[/dim]"
            )

    # Increment ref count
    forward.ref_count += 1

    try:
        yield
    finally:
        # Decrement ref count
        forward.ref_count -= 1

        if console:
            console.print(
                f"[dim]Released port-forward reference (refs={forward.ref_count})[/dim]"
            )

        # Clean up if last reference
        if forward.ref_count == 0:
            if forward.process.poll() is None:
                if console:
                    console.print("[dim]Stopping port-forward...[/dim]")
                forward.process.terminate()
                try:
                    forward.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    forward.process.kill()
                    forward.process.wait()

            # Remove from registry (check identity in case it was replaced)
            if key in _active_forwards and _active_forwards[key] is forward:
                del _active_forwards[key]

            if console:
                console.print("[dim]Port-forward stopped[/dim]")


def with_postgres_port_forward(
    namespace: str | None = None,
    *,
    pod_name: str | None = None,
    pod_label: str | None = None,
    local_port: int = DEFAULT_CONSTANTS.DEFAULT_EPHEMERAL_PORT,
    remote_port: int = 5432,
    wait_time: float = 5.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to automatically set up port forwarding for a function.

    This decorator wraps a function with the postgres_port_forward context manager,
    automatically handling port forwarding setup and teardown.

    Args:
        namespace: Kubernetes namespace (if None, tries to get from function kwargs)
        pod_name: Name of the PostgreSQL pod (if None, tries to get from function kwargs)
        local_port: Local port to forward to (default: 5432)
        remote_port: Remote port on the pod (default: 5432)
        wait_time: Time to wait for port-forward to be ready (default: 2.0s)

    Returns:
        Decorator function

    Example:
        >>> @with_postgres_port_forward(namespace="api-forge-prod", pod_name="postgres-0")
        ... def initialize_database():
        ...     # Port forwarding is active here
        ...     conn = psycopg2.connect(host="localhost", port=5432, ...)
        ...     # Do database operations
        ...
        >>> # Or let it extract from function arguments:
        >>> @with_postgres_port_forward()
        ... def verify_db(namespace: str, pod: str):
        ...     # Decorator will use namespace and pod arguments
        ...     conn = psycopg2.connect(host="localhost", port=5432, ...)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Try to extract namespace and pod_name from function arguments
            actual_namespace = namespace
            actual_pod_name = pod_name
            actual_pod_label = pod_label

            # If not provided to decorator, try to get from kwargs
            if actual_namespace is None:
                actual_namespace = kwargs.get("namespace")
            if actual_pod_name is None:
                actual_pod_name = kwargs.get("pod_name") or kwargs.get("pod")
            if actual_pod_label is None:
                actual_pod_label = kwargs.get("pod_label")

            # Validate we have required parameters
            if not actual_namespace or (not actual_pod_name and not actual_pod_label):
                raise ValueError(
                    "namespace and pod_name or pod_label must be provided either to decorator "
                    "or as function arguments"
                )

            # Execute function within port-forward context
            with postgres_port_forward(
                namespace=actual_namespace,
                pod_name=actual_pod_name,
                pod_label=actual_pod_label,
                local_port=local_port,
                remote_port=remote_port,
                wait_time=wait_time,
            ):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def with_postgres_port_forward_if_needed(
    namespace: str | None = None,
    *,
    pod_name: str | None = None,
    pod_label: str | None = None,
    local_port: int = DEFAULT_CONSTANTS.DEFAULT_EPHEMERAL_PORT,
    remote_port: int = 5432,
    wait_time: float = 5.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator that sets up port forwarding only if bundled postgres is enabled.

    When bundled postgres is disabled (using external database), this is a no-op.
    When bundled postgres is enabled, this wraps the function with port forwarding.

    Args:
        namespace: Kubernetes namespace (if None, tries to get from function kwargs)
        pod_name: Name of the PostgreSQL pod (if None, tries to get from function kwargs)
        pod_label: Label selector to find pod (if pod_name not provided)
        local_port: Local port to forward to (default: 5432)
        remote_port: Remote port on the pod (default: 5432)
        wait_time: Time to wait for port-forward to be ready (default: 5.0s)

    Returns:
        Decorator function

    Example:
        >>> @with_postgres_port_forward_if_needed(namespace="api-forge-prod")
        ... def verify_database():
        ...     # If bundled postgres: port forwarding is active
        ...     # If external postgres: no port forwarding needed
        ...     conn = psycopg2.connect(...)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            actual_namespace = namespace
            actual_pod_name = pod_name
            actual_pod_label = pod_label

            if actual_namespace is None:
                actual_namespace = kwargs.get("namespace")
            if actual_pod_name is None:
                actual_pod_name = kwargs.get("pod_name") or kwargs.get("pod")
            if actual_pod_label is None:
                actual_pod_label = kwargs.get("pod_label")

            # Note: postgres_port_forward_if_needed handles the bundled check,
            # but we still need namespace validation when bundled is enabled
            if is_bundled_postgres_enabled():
                if not actual_namespace or (
                    not actual_pod_name and not actual_pod_label
                ):
                    raise ValueError(
                        "namespace and pod_name or pod_label must be provided either to decorator "
                        "or as function arguments"
                    )

            with postgres_port_forward_if_needed(
                namespace=actual_namespace or "",
                pod_name=actual_pod_name,
                pod_label=actual_pod_label,
                local_port=local_port,
                remote_port=remote_port,
                wait_time=wait_time,
            ):
                return func(*args, **kwargs)

        return wrapper

    return decorator


@contextmanager
def postgres_port_forward_if_needed(
    namespace: str,
    console: Console | None = None,
    *,
    pod_name: str | None = None,
    pod_label: str | None = None,
    local_port: int = DEFAULT_CONSTANTS.DEFAULT_EPHEMERAL_PORT,
    remote_port: int = 5432,
    wait_time: float = 2.0,
    reuse_existing: bool = True,
) -> Generator[None]:
    """Context manager that sets up port forwarding only if bundled postgres is enabled.

    When bundled postgres is disabled (using external database), this is a no-op.
    When bundled postgres is enabled, this sets up kubectl port-forward.

    Args:
        namespace: Kubernetes namespace containing the pod
        console: Rich console for output
        pod_name: Name of the PostgreSQL pod
        pod_label: Label selector to find pod (if pod_name not provided)
        local_port: Local port to forward to (default: 5432)
        remote_port: Remote port on the pod (default: 5432)
        wait_time: Time to wait for port-forward to be ready (default: 2.0s)
        reuse_existing: If True, reuse existing forward if available (default: True)

    Yields:
        None

    Example:
        >>> with postgres_port_forward_if_needed("api-forge-prod", pod_name="postgres-0"):
        ...     # If bundled postgres: port forwarding is active
        ...     # If external postgres: no port forwarding, direct connection
        ...     conn = psycopg2.connect(...)
    """
    if not is_bundled_postgres_enabled():
        # No port forwarding needed for external postgres
        yield
        return

    # Use the regular port forward context manager
    with postgres_port_forward(
        namespace=namespace,
        console=console,
        pod_name=pod_name,
        pod_label=pod_label,
        local_port=local_port,
        remote_port=remote_port,
        wait_time=wait_time,
        reuse_existing=reuse_existing,
    ):
        yield
