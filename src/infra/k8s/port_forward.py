"""PostgreSQL port forwarding context manager for Kubernetes.

Provides automatic port forwarding to PostgreSQL pods in Kubernetes
for CLI operations. Uses the shared PortForwardRegistry for lifecycle management.
"""

import subprocess
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar

from rich.progress import Console

from src.infra.constants import DEFAULT_CONSTANTS
from src.infra.k8s.helpers import (
    get_k8s_controller,
    get_namespace,
    get_postgres_label,
)
from src.infra.k8s.utils import run_sync
from src.infra.port_forward import PortForwardError, PortForwardRegistry
from src.infra.utils.service_config import is_bundled_postgres_enabled

# Type variable for function return type
T = TypeVar("T")

# Module-level registry instance
_registry = PortForwardRegistry()


@dataclass
class PortForwardKey:
    """Key for tracking active K8s port forwards."""

    namespace: str
    pod_name: str
    local_port: int
    remote_port: int

    def __hash__(self) -> int:
        return hash((self.namespace, self.pod_name, self.local_port, self.remote_port))


def _get_postgres_pod() -> str | None:
    """Get the name of the PostgreSQL pod."""
    controller = get_k8s_controller()
    p_pods = run_sync(
        controller.get_pods(get_namespace(), label_selector=get_postgres_label())
    )
    if p_pods:
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
    """
    if not pod_name:
        if not pod_label:
            raise PortForwardError("Either pod_name or pod_label must be provided")
        pod_name = _get_postgres_pod()
        if not pod_name:
            raise PortForwardError(
                f"No pod found with label '{pod_label}' in namespace '{namespace}'"
            )

    key = PortForwardKey(
        namespace=namespace,
        pod_name=pod_name,
        local_port=local_port,
        remote_port=remote_port,
    )

    def start_fn() -> subprocess.Popen[str]:
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

        import time

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

        if console:
            console.print(
                f"[dim]Port-forward active: localhost:{local_port} -> {pod_name}:{remote_port}[/dim]"
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

    Args:
        namespace: Kubernetes namespace (if None, tries to get from function kwargs)
        pod_name: Name of the PostgreSQL pod (if None, tries to get from function kwargs)
        pod_label: Label selector to find pod (if pod_name not provided)
        local_port: Local port to forward to (default: 5432)
        remote_port: Remote port on the pod (default: 5432)
        wait_time: Time to wait for port-forward to be ready (default: 2.0s)

    Returns:
        Decorator function
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

            if not actual_namespace or (not actual_pod_name and not actual_pod_label):
                raise ValueError(
                    "namespace and pod_name or pod_label must be provided either to decorator "
                    "or as function arguments"
                )

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

    Args:
        namespace: Kubernetes namespace (if None, tries to get from function kwargs)
        pod_name: Name of the PostgreSQL pod (if None, tries to get from function kwargs)
        pod_label: Label selector to find pod (if pod_name not provided)
        local_port: Local port to forward to (default: 5432)
        remote_port: Remote port on the pod (default: 5432)
        wait_time: Time to wait for port-forward to be ready (default: 5.0s)

    Returns:
        Decorator function
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
    """
    if not is_bundled_postgres_enabled():
        yield
        return

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
