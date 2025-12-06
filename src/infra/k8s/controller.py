"""Abstract Kubernetes controller interface.

Defines the contract for Kubernetes operations that can be implemented
by different backends (kubectl subprocess, kr8s library, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# =============================================================================
# Data Types
# =============================================================================


@dataclass
class CommandResult:
    """Result of a command execution."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


@dataclass
class PodInfo:
    """Information about a Kubernetes pod."""

    name: str
    status: str
    restarts: int = 0
    creation_timestamp: str = ""
    job_owner: str = ""
    ip: str = ""
    node: str = ""


@dataclass
class ReplicaSetInfo:
    """Information about a Kubernetes ReplicaSet."""

    name: str
    replicas: int
    revision: str = ""
    created_at: datetime | None = None
    owner_deployment: str | None = None


@dataclass
class JobInfo:
    """Information about a Kubernetes Job."""

    name: str
    status: str  # "Running", "Complete", "Failed", "Unknown"


@dataclass
class ServiceInfo:
    """Information about a Kubernetes Service."""

    name: str
    type: str
    cluster_ip: str
    external_ip: str = ""
    ports: str = ""


@dataclass
class ClusterIssuerStatus:
    """Status of a cert-manager ClusterIssuer."""

    exists: bool
    ready: bool
    message: str = ""


# =============================================================================
# Abstract Controller
# =============================================================================


class KubernetesController(ABC):
    """Abstract base class for Kubernetes operations.

    All methods are async to support both sync (kubectl) and async (kr8s)
    implementations. Use `run_sync()` to call from synchronous code.

    Example:
        from src.infra.k8s import KubectlController, run_sync

        controller = KubectlController()
        pods = run_sync(controller.get_pods("my-namespace"))
    """

    # =========================================================================
    # Cluster Context
    # =========================================================================

    @abstractmethod
    async def get_current_context(self) -> str:
        """Get the current kubectl context name.

        Returns:
            Context name, or "unknown" if detection fails
        """
        ...

    @abstractmethod
    async def is_minikube_context(self) -> bool:
        """Check if the current kubectl context is Minikube.

        Returns:
            True if current context is minikube, False otherwise
        """
        ...

    # =========================================================================
    # Namespace Operations
    # =========================================================================

    @abstractmethod
    async def namespace_exists(self, namespace: str) -> bool:
        """Check if a namespace exists.

        Args:
            namespace: Namespace to check

        Returns:
            True if the namespace exists, False otherwise
        """
        ...

    @abstractmethod
    async def delete_namespace(
        self,
        namespace: str,
        *,
        wait: bool = True,
        timeout: str = "120s",
    ) -> CommandResult:
        """Delete a Kubernetes namespace and all its resources.

        Warning: This is a destructive operation.

        Args:
            namespace: Namespace to delete
            wait: Whether to wait for deletion to complete
            timeout: Maximum time to wait

        Returns:
            CommandResult with deletion status
        """
        ...

    @abstractmethod
    async def delete_pvcs(self, namespace: str) -> CommandResult:
        """Delete all PersistentVolumeClaims in a namespace.

        Args:
            namespace: Kubernetes namespace

        Returns:
            CommandResult with deletion status
        """
        ...

    # =========================================================================
    # Resource Operations
    # =========================================================================

    @abstractmethod
    async def apply_manifest(self, manifest_path: Path) -> CommandResult:
        """Apply a Kubernetes manifest file.

        Args:
            manifest_path: Path to the YAML manifest file

        Returns:
            CommandResult with apply status
        """
        ...

    @abstractmethod
    async def delete_resources_by_label(
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
        ...

    @abstractmethod
    async def delete_helm_secrets(
        self,
        namespace: str,
        release_name: str,
    ) -> CommandResult:
        """Delete Helm release metadata secrets.

        Useful for cleaning up stuck Helm releases.

        Args:
            namespace: Kubernetes namespace
            release_name: Helm release name

        Returns:
            CommandResult with deletion status
        """
        ...

    # =========================================================================
    # Deployment Operations
    # =========================================================================

    @abstractmethod
    async def get_deployments(self, namespace: str) -> list[str]:
        """Get list of deployment names in a namespace.

        Args:
            namespace: Kubernetes namespace

        Returns:
            List of deployment names
        """
        ...

    @abstractmethod
    async def rollout_restart(
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
        """
        ...

    @abstractmethod
    async def rollout_status(
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
        """
        ...

    @abstractmethod
    async def get_deployment_revision(
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
        ...

    # =========================================================================
    # ReplicaSet Operations
    # =========================================================================

    @abstractmethod
    async def get_replicasets(self, namespace: str) -> list[ReplicaSetInfo]:
        """Get all ReplicaSets in a namespace.

        Args:
            namespace: Kubernetes namespace

        Returns:
            List of ReplicaSetInfo objects with parsed metadata
        """
        ...

    @abstractmethod
    async def delete_replicaset(
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
        ...

    @abstractmethod
    async def scale_replicaset(
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
        ...

    # =========================================================================
    # Pod Operations
    # =========================================================================

    @abstractmethod
    async def get_pods(self, namespace: str) -> list[PodInfo]:
        """Get all pods in a namespace with their status.

        Args:
            namespace: Kubernetes namespace

        Returns:
            List of PodInfo objects with pod details
        """
        ...

    @abstractmethod
    async def wait_for_pods(
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
        """
        ...

    @abstractmethod
    async def check_pods_ready(
        self,
        pod_selector: str,
        namespace: str,
        timeout: int = 60,
    ) -> bool:
        """Check if Kubernetes pods matching selector are ready.

        Args:
            pod_selector: Label selector or pod name
            namespace: Kubernetes namespace
            timeout: Maximum time to wait in seconds

        Returns:
            True if all matching pods are ready, False otherwise
        """
        ...

    @abstractmethod
    async def get_pod_logs(
        self,
        namespace: str,
        pod: str | None = None,
        *,
        container: str | None = None,
        label_selector: str | None = None,
        follow: bool = False,
        tail: int = 100,
        previous: bool = False,
    ) -> CommandResult:
        """Get logs from Kubernetes pods.

        Args:
            namespace: Kubernetes namespace
            pod: Specific pod name, or None to use label_selector
            container: Container name (if pod has multiple containers)
            label_selector: Label selector for pods (if pod is None)
            follow: Whether to follow log output
            tail: Number of lines to show from the end
            previous: Show logs from previous container instance

        Returns:
            CommandResult with logs in stdout
        """
        ...

    # =========================================================================
    # Job Operations
    # =========================================================================

    @abstractmethod
    async def get_jobs(self, namespace: str) -> list[JobInfo]:
        """Get all jobs in a namespace with their status.

        Args:
            namespace: Kubernetes namespace

        Returns:
            List of JobInfo objects
        """
        ...

    # =========================================================================
    # Service Operations
    # =========================================================================

    @abstractmethod
    async def get_services(self, namespace: str) -> list[ServiceInfo]:
        """Get all services in a namespace.

        Args:
            namespace: Kubernetes namespace

        Returns:
            List of ServiceInfo objects
        """
        ...

    # =========================================================================
    # Status Display (raw output for display purposes)
    # =========================================================================

    @abstractmethod
    async def get_pods_wide(self, namespace: str) -> str:
        """Get pods in wide format for display.

        Args:
            namespace: Kubernetes namespace

        Returns:
            Raw kubectl output in wide format
        """
        ...

    @abstractmethod
    async def get_services_output(self, namespace: str) -> str:
        """Get services output for display.

        Args:
            namespace: Kubernetes namespace

        Returns:
            Raw kubectl output for services
        """
        ...

    # =========================================================================
    # Cert-Manager Operations
    # =========================================================================

    @abstractmethod
    async def check_cert_manager_installed(self) -> bool:
        """Check if cert-manager is installed in the cluster.

        Returns:
            True if cert-manager pods are running, False otherwise
        """
        ...

    @abstractmethod
    async def get_cluster_issuer_status(
        self,
        issuer_name: str,
    ) -> ClusterIssuerStatus:
        """Get the status of a cert-manager ClusterIssuer.

        Args:
            issuer_name: Name of the ClusterIssuer

        Returns:
            ClusterIssuerStatus with exists, ready, and message
        """
        ...

    @abstractmethod
    async def get_cluster_issuer_yaml(self, issuer_name: str) -> str | None:
        """Get the YAML representation of a ClusterIssuer.

        Args:
            issuer_name: Name of the ClusterIssuer

        Returns:
            YAML string, or None if not found
        """
        ...
