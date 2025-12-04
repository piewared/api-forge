"""Kubectl command abstractions.

This module provides commands for Kubernetes resource management via kubectl,
organized into logical groups for namespaces, deployments, ReplicaSets, and pods.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from .types import CommandResult, ReplicaSetInfo

if TYPE_CHECKING:
    from .runner import CommandRunner


class KubectlCommands:
    """Kubectl-related shell commands.

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
            runner: Command runner for executing shell commands
        """
        self._runner = runner

    # =========================================================================
    # Cluster Context
    # =========================================================================

    def is_minikube_context(self) -> bool:
        """Check if the current kubectl context is Minikube.

        Returns:
            True if current context is minikube, False otherwise
        """
        result = self._runner.run(
            ["kubectl", "config", "current-context"],
            capture_output=True,
        )
        if not result.success:
            return False
        return "minikube" in result.stdout.strip().lower()

    def get_current_context(self) -> str:
        """Get the current kubectl context name.

        Returns:
            Context name, or "unknown" if detection fails
        """
        result = self._runner.run(
            ["kubectl", "config", "current-context"],
            capture_output=True,
        )
        return result.stdout.strip() if result.success else "unknown"

    # =========================================================================
    # Namespace Management
    # =========================================================================

    def namespace_exists(self, namespace: str) -> bool:
        """Check if a namespace exists.

        Args:
            namespace: Namespace to check

        Returns:
            True if the namespace exists, False otherwise
        """
        result = self._runner.run(
            ["kubectl", "get", "namespace", namespace],
            capture_output=True,
        )
        return result.success

    def delete_namespace(
        self,
        namespace: str,
        *,
        wait: bool = True,
        timeout: str = "120s",
    ) -> CommandResult:
        """Delete a Kubernetes namespace and all its resources.

        Warning: This is a destructive operation that deletes all resources
        in the namespace.

        Args:
            namespace: Namespace to delete
            wait: Whether to wait for deletion to complete
            timeout: Maximum time to wait

        Returns:
            CommandResult with deletion status
        """
        cmd = ["kubectl", "delete", "namespace", namespace]
        if wait:
            cmd.append("--wait=true")
            cmd.extend(["--timeout", timeout])
        return self._runner.run(cmd)

    def delete_pvcs(self, namespace: str) -> CommandResult:
        """Delete all PersistentVolumeClaims in a namespace.

        Args:
            namespace: Kubernetes namespace

        Returns:
            CommandResult with deletion status
        """
        return self._runner.run(
            ["kubectl", "delete", "pvc", "--all", "-n", namespace],
            capture_output=True,
        )

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
        """Delete Kubernetes resources matching a label selector.

        Args:
            resource_types: Comma-separated resource types
                           (e.g., "all,configmap,secret")
            namespace: Kubernetes namespace
            label_selector: Label selector
                           (e.g., "app.kubernetes.io/instance=my-app")
            force: Whether to force delete (bypass graceful deletion)

        Returns:
            CommandResult with deletion status
        """
        cmd = [
            "kubectl",
            "delete",
            resource_types,
            "-n",
            namespace,
            "-l",
            label_selector,
        ]
        if force:
            cmd.extend(["--force", "--grace-period=0"])
        return self._runner.run(cmd)

    def delete_helm_secrets(
        self,
        namespace: str,
        release_name: str,
    ) -> CommandResult:
        """Delete Helm release metadata secrets.

        This is useful for cleaning up stuck Helm releases that can't
        be uninstalled normally.

        Args:
            namespace: Kubernetes namespace
            release_name: Helm release name

        Returns:
            CommandResult with deletion status
        """
        return self._runner.run(
            [
                "kubectl",
                "delete",
                "secret",
                "-n",
                namespace,
                "-l",
                f"name={release_name},owner=helm",
            ]
        )

    # =========================================================================
    # ReplicaSet Operations
    # =========================================================================

    def get_replicasets(self, namespace: str) -> list[ReplicaSetInfo]:
        """Get all ReplicaSets in a namespace.

        Args:
            namespace: Kubernetes namespace

        Returns:
            List of ReplicaSetInfo objects with parsed metadata
        """
        result = self._runner.run(
            ["kubectl", "get", "replicasets", "-n", namespace, "-o", "json"]
        )
        if not result.success or not result.stdout:
            return []

        try:
            data = json.loads(result.stdout)
            replicasets = []

            for rs in data.get("items", []):
                metadata = rs.get("metadata", {})
                spec = rs.get("spec", {})
                annotations = metadata.get("annotations", {})
                owner_refs = metadata.get("ownerReferences", [])

                # Parse creation timestamp
                created_at = None
                if creation_ts := metadata.get("creationTimestamp"):
                    try:
                        created_at = datetime.fromisoformat(
                            creation_ts.replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass

                # Get owner deployment name
                owner_deployment = None
                if owner_refs:
                    owner_deployment = owner_refs[0].get("name")

                replicasets.append(
                    ReplicaSetInfo(
                        name=metadata.get("name", ""),
                        replicas=spec.get("replicas", 0),
                        revision=annotations.get(
                            "deployment.kubernetes.io/revision", ""
                        ),
                        created_at=created_at,
                        owner_deployment=owner_deployment,
                    )
                )

            return replicasets
        except json.JSONDecodeError:
            return []

    def delete_replicaset(
        self,
        name: str,
        namespace: str,
    ) -> CommandResult:
        """Delete a specific ReplicaSet.

        Args:
            name: ReplicaSet name
            namespace: Kubernetes namespace

        Returns:
            CommandResult with deletion status
        """
        return self._runner.run(
            ["kubectl", "delete", "replicaset", name, "-n", namespace]
        )

    def scale_replicaset(
        self,
        name: str,
        namespace: str,
        replicas: int,
    ) -> CommandResult:
        """Scale a ReplicaSet to a specific number of replicas.

        Args:
            name: ReplicaSet name
            namespace: Kubernetes namespace
            replicas: Desired number of replicas

        Returns:
            CommandResult with scale status
        """
        return self._runner.run(
            [
                "kubectl",
                "scale",
                "replicaset",
                name,
                f"--replicas={replicas}",
                "-n",
                namespace,
            ]
        )

    # =========================================================================
    # Deployment Operations
    # =========================================================================

    def get_deployments(self, namespace: str) -> list[str]:
        """Get list of deployment names in a namespace.

        Args:
            namespace: Kubernetes namespace

        Returns:
            List of deployment names
        """
        result = self._runner.run(
            [
                "kubectl",
                "get",
                "deployments",
                "-n",
                namespace,
                "-o",
                "jsonpath={.items[*].metadata.name}",
            ]
        )
        if not result.success or not result.stdout:
            return []
        return result.stdout.strip().split()

    def rollout_restart(
        self,
        resource_type: str,
        namespace: str,
        name: str | None = None,
    ) -> CommandResult:
        """Trigger a rolling restart of a deployment/daemonset/statefulset.

        Args:
            resource_type: Resource type ("deployment", "daemonset", "statefulset")
            namespace: Kubernetes namespace
            name: Specific resource name, or None to restart all of that type

        Returns:
            CommandResult with restart status

        Example:
            >>> # Restart all deployments
            >>> kubectl.rollout_restart("deployment", "production")
            >>> # Restart specific deployment
            >>> kubectl.rollout_restart("deployment", "production", "api-server")
        """
        if name:
            cmd = [
                "kubectl",
                "rollout",
                "restart",
                resource_type,
                name,
                "-n",
                namespace,
            ]
        else:
            cmd = ["kubectl", "rollout", "restart", resource_type, "-n", namespace]
        return self._runner.run(cmd, capture_output=True)

    def rollout_status(
        self,
        resource_type: str,
        namespace: str,
        name: str | None = None,
        *,
        timeout: str = "300s",
    ) -> CommandResult:
        """Wait for a rollout to complete.

        Blocks until the rollout finishes (all pods are ready) or times out.

        Args:
            resource_type: Resource type ("deployment", "daemonset", "statefulset")
            namespace: Kubernetes namespace
            name: Specific resource name, or None to wait for all of that type
            timeout: Maximum time to wait for rollout to complete

        Returns:
            CommandResult with rollout status

        Example:
            >>> # Wait for all deployments to be ready
            >>> kubectl.rollout_status("deployment", "production")
            >>> # Wait for specific deployment
            >>> kubectl.rollout_status("deployment", "production", "api-server")
        """
        if name:
            cmd = [
                "kubectl",
                "rollout",
                "status",
                resource_type,
                name,
                "-n",
                namespace,
                f"--timeout={timeout}",
            ]
        else:
            cmd = [
                "kubectl",
                "rollout",
                "status",
                resource_type,
                "-n",
                namespace,
                f"--timeout={timeout}",
            ]
        return self._runner.run(cmd, capture_output=False)

    def get_deployment_revision(
        self,
        name: str,
        namespace: str,
    ) -> str | None:
        """Get the current revision number of a deployment.

        Args:
            name: Deployment name
            namespace: Kubernetes namespace

        Returns:
            Revision number as string, or None if not found
        """
        result = self._runner.run(
            [
                "kubectl",
                "get",
                "deployment",
                name,
                "-n",
                namespace,
                "-o",
                "jsonpath={.metadata.annotations.deployment\\.kubernetes\\.io/revision}",
            ]
        )
        return result.stdout.strip() if result.success and result.stdout else None

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
        """Wait for pods matching a selector to reach a condition.

        Args:
            namespace: Kubernetes namespace
            label_selector: Label selector for pods
            condition: Condition to wait for (e.g., "ready", "delete")
            timeout: Maximum time to wait

        Returns:
            CommandResult with wait status

        Example:
            >>> kubectl.wait_for_pods(
            ...     "production",
            ...     "app.kubernetes.io/component=application",
            ...     timeout="120s",
            ... )
        """
        return self._runner.run(
            [
                "kubectl",
                "wait",
                "--for",
                f"condition={condition}",
                "pod",
                "-l",
                label_selector,
                "-n",
                namespace,
                f"--timeout={timeout}",
            ],
            capture_output=False,
        )

    def get_pods(self, namespace: str) -> list[dict[str, str | int]]:
        """Get all pods in a namespace with their status.

        Args:
            namespace: Kubernetes namespace

        Returns:
            List of dicts with pod name, status, restarts, creation timestamp,
            and job owner (if pod is owned by a Job)
        """
        result = self._runner.run(
            ["kubectl", "get", "pods", "-n", namespace, "-o", "json"],
            capture_output=True,
        )
        if not result.success or not result.stdout:
            return []

        try:
            data = json.loads(result.stdout)
            pods = []

            for pod in data.get("items", []):
                metadata = pod.get("metadata", {})
                name = metadata.get("name", "")
                creation_timestamp = metadata.get("creationTimestamp", "")
                status = pod.get("status", {})

                # Check if pod is owned by a Job
                job_owner = ""
                for owner_ref in metadata.get("ownerReferences", []):
                    if owner_ref.get("kind") == "Job":
                        job_owner = owner_ref.get("name", "")
                        break

                # Determine pod status
                phase = status.get("phase", "Unknown")
                container_statuses = status.get("containerStatuses", [])

                # Check for specific states
                pod_status = phase
                restarts = 0

                for cs in container_statuses:
                    restarts += cs.get("restartCount", 0)
                    state = cs.get("state", {})
                    if "waiting" in state:
                        reason = state["waiting"].get("reason", "")
                        if reason:
                            pod_status = reason  # e.g., CrashLoopBackOff
                    elif "terminated" in state:
                        reason = state["terminated"].get("reason", "")
                        if reason == "Error":
                            pod_status = "Error"

                pods.append(
                    {
                        "name": name,
                        "status": pod_status,
                        "restarts": restarts,
                        "creationTimestamp": creation_timestamp,
                        "jobOwner": job_owner,
                    }
                )

            return pods
        except json.JSONDecodeError:
            return []

    # =========================================================================
    # Job Operations
    # =========================================================================

    def get_jobs(self, namespace: str) -> list[dict[str, str]]:
        """Get all jobs in a namespace with their status.

        Args:
            namespace: Kubernetes namespace

        Returns:
            List of dicts with job name and status (Running/Complete/Failed)
        """
        result = self._runner.run(
            ["kubectl", "get", "jobs", "-n", namespace, "-o", "json"],
            capture_output=True,
        )
        if not result.success or not result.stdout:
            return []

        try:
            data = json.loads(result.stdout)
            jobs = []

            for job in data.get("items", []):
                name = job.get("metadata", {}).get("name", "")
                status = job.get("status", {})

                # Determine job status
                if status.get("succeeded", 0) > 0:
                    job_status = "Complete"
                elif status.get("failed", 0) > 0:
                    job_status = "Failed"
                elif status.get("active", 0) > 0:
                    job_status = "Running"
                else:
                    job_status = "Unknown"

                jobs.append(
                    {
                        "name": name,
                        "status": job_status,
                    }
                )

            return jobs
        except json.JSONDecodeError:
            return []
