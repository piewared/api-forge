"""Kubectl command abstractions.

This module provides commands for Kubernetes resource management via kubectl,
delegating to Kr8sController for the actual operations.

This is a sync wrapper around the async Kr8sController for backward
compatibility with existing code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.infra.k8s import Kr8sController, run_sync
from src.infra.k8s.controller import (
    CommandResult,
    JobInfo,
    PodInfo,
    ReplicaSetInfo,
)

if TYPE_CHECKING:
    from .runner import CommandRunner


class KubectlCommands:
    """Kubectl-related shell commands.

    This is a sync wrapper around Kr8sController that provides backward
    compatibility with existing code. All methods delegate to the async
    controller using run_sync().

    Provides operations for:
    - Cluster context detection
    - Namespace management
    - Deployment operations (rollout, restart, status)
    - ReplicaSet management (list, scale, delete)
    - Pod management (wait for conditions)
    - Resource deletion by label
    """

    def __init__(self, runner: CommandRunner) -> None:
        """Initialize kubectl commands.

        Args:
            runner: Command runner (kept for interface compatibility, not used)
        """
        # Keep runner reference for interface compatibility
        self._runner = runner
        # Delegate to the async controller
        self._controller = Kr8sController()

    # =========================================================================
    # Cluster Context
    # =========================================================================

    def is_minikube_context(self) -> bool:
        """Check if the current kubectl context is Minikube."""
        return run_sync(self._controller.is_minikube_context())

    def get_current_context(self) -> str:
        """Get the current kubectl context name."""
        return run_sync(self._controller.get_current_context())

    # =========================================================================
    # Namespace Management
    # =========================================================================

    def namespace_exists(self, namespace: str) -> bool:
        """Check if a namespace exists."""
        return run_sync(self._controller.namespace_exists(namespace))

    def delete_namespace(
        self,
        namespace: str,
        *,
        wait: bool = True,
        timeout: str = "120s",
    ) -> CommandResult:
        """Delete a Kubernetes namespace and all its resources."""
        return run_sync(
            self._controller.delete_namespace(namespace, wait=wait, timeout=timeout)
        )

    def delete_pvcs(self, namespace: str) -> CommandResult:
        """Delete all PersistentVolumeClaims in a namespace."""
        return run_sync(self._controller.delete_pvcs(namespace))

    # =========================================================================
    # Resource Deletion
    # =========================================================================

    def delete_resources_by_label(
        self,
        resource_types: str,
        namespace: str,
        label_selector: str,
        *,
        force: bool = False,
    ) -> CommandResult:
        """Delete Kubernetes resources matching a label selector."""
        return run_sync(
            self._controller.delete_resources_by_label(
                resource_types, namespace, label_selector, force=force
            )
        )

    def delete_helm_secrets(
        self,
        namespace: str,
        release_name: str,
    ) -> CommandResult:
        """Delete Helm release metadata secrets."""
        return run_sync(self._controller.delete_helm_secrets(namespace, release_name))

    # =========================================================================
    # ReplicaSet Operations
    # =========================================================================

    def get_replicasets(self, namespace: str) -> list[ReplicaSetInfo]:
        """Get all ReplicaSets in a namespace."""
        return run_sync(self._controller.get_replicasets(namespace))

    def delete_replicaset(
        self,
        name: str,
        namespace: str,
    ) -> CommandResult:
        """Delete a specific ReplicaSet."""
        return run_sync(self._controller.delete_replicaset(name, namespace))

    def scale_replicaset(
        self,
        name: str,
        namespace: str,
        replicas: int,
    ) -> CommandResult:
        """Scale a ReplicaSet to a specific number of replicas."""
        return run_sync(self._controller.scale_replicaset(name, namespace, replicas))

    # =========================================================================
    # Deployment Operations
    # =========================================================================

    def get_deployments(self, namespace: str) -> list[str]:
        """Get list of deployment names in a namespace."""
        return run_sync(self._controller.get_deployments(namespace))

    def rollout_restart(
        self,
        resource_type: str,
        namespace: str,
        name: str | None = None,
    ) -> CommandResult:
        """Trigger a rolling restart of a deployment/daemonset/statefulset."""
        return run_sync(
            self._controller.rollout_restart(resource_type, namespace, name)
        )

    def rollout_status(
        self,
        resource_type: str,
        namespace: str,
        name: str | None = None,
        *,
        timeout: str = "300s",
    ) -> CommandResult:
        """Wait for a rollout to complete."""
        return run_sync(
            self._controller.rollout_status(
                resource_type, namespace, name, timeout=timeout
            )
        )

    def get_deployment_revision(
        self,
        name: str,
        namespace: str,
    ) -> str | None:
        """Get the current revision number of a deployment."""
        return run_sync(self._controller.get_deployment_revision(name, namespace))

    # =========================================================================
    # Pod Operations
    # =========================================================================

    def wait_for_pods(
        self,
        namespace: str,
        label_selector: str,
        *,
        condition: str = "ready",
        timeout: str = "300s",
    ) -> CommandResult:
        """Wait for pods matching a selector to reach a condition."""
        return run_sync(
            self._controller.wait_for_pods(
                namespace, label_selector, condition=condition, timeout=timeout
            )
        )

    def get_pods(self, namespace: str) -> list[PodInfo]:
        """Get all pods in a namespace with their status.

        Note: Return type changed from list[dict] to list[PodInfo].
        Access fields as attributes: pod.name, pod.status, etc.
        """
        return run_sync(self._controller.get_pods(namespace))

    # =========================================================================
    # Job Operations
    # =========================================================================

    def get_jobs(self, namespace: str) -> list[JobInfo]:
        """Get all jobs in a namespace with their status.

        Note: Return type changed from list[dict] to list[JobInfo].
        Access fields as attributes: job.name, job.status
        """
        return run_sync(self._controller.get_jobs(namespace))
