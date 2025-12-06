"""Kubernetes infrastructure abstraction layer.

This module provides a clean abstraction over Kubernetes operations,
supporting multiple backends (kubectl subprocess, kr8s library).

Example:
    from src.infra.k8s import KubernetesController, KubectlController, run_sync

    # Create controller
    controller = KubectlController()

    # Use async methods in sync context
    exists = run_sync(controller.namespace_exists("my-namespace"))
    pods = run_sync(controller.get_pods("my-namespace"))
"""

from .controller import (
    ClusterIssuerStatus,
    CommandResult,
    JobInfo,
    KubernetesController,
    PodInfo,
    ReplicaSetInfo,
    ServiceInfo,
)
from .kubectl_controller import KubectlController
from .utils import run_sync

__all__ = [
    # Controller classes
    "KubernetesController",
    "KubectlController",
    # Data classes
    "CommandResult",
    "PodInfo",
    "ReplicaSetInfo",
    "JobInfo",
    "ServiceInfo",
    "ClusterIssuerStatus",
    # Utilities
    "run_sync",
]
