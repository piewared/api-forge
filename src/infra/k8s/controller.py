"""Abstract Kubernetes controller interface.

Defines the contract for Kubernetes operations that can be implemented
by different backends (kubectl subprocess, kr8s library, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.infra.k8s.utils import run_sync

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
    async def resource_exists(
        self,
        resource_type: str,
        name: str,
        namespace: str,
    ) -> bool:
        """Check if a Kubernetes resource exists.

        Args:
            resource_type: Resource type (e.g., "statefulset", "deployment", "pod")
            name: Resource name
            namespace: Kubernetes namespace

        Returns:
            True if the resource exists, False otherwise
        """
        ...

    @abstractmethod
    async def delete_resource(
        self,
        resource_type: str,
        name: str,
        namespace: str,
        *,
        cascade: str | None = None,
        wait: bool = True,
    ) -> CommandResult:
        """Delete a specific Kubernetes resource by name.

        Args:
            resource_type: Resource type (e.g., "statefulset", "deployment", "pod")
            name: Resource name
            namespace: Kubernetes namespace
            cascade: Cascade deletion policy (None uses k8s default):
                     - "background": Delete dependents in background
                     - "foreground": Delete dependents in foreground
                     - "orphan": Leave dependents running (don't delete)
            wait: Whether to wait for deletion to complete

        Returns:
            CommandResult with deletion status
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
        cascade: str | None = None,
    ) -> CommandResult:
        """Delete Kubernetes resources matching a label selector.

        Args:
            resource_types: Comma-separated resource types
                           (e.g., "all,configmap,secret")
            namespace: Kubernetes namespace
            label_selector: Label selector
                           (e.g., "app.kubernetes.io/instance=my-app")
            force: Whether to force delete (bypass graceful deletion)
            cascade: Cascade deletion policy (None uses k8s default):
                     - "background": Delete dependents in background
                     - "foreground": Delete dependents in foreground
                     - "orphan": Leave dependents running (don't delete)

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
    async def get_pods(
        self,
        namespace: str,
        label_selector: str | None = None,
    ) -> list[PodInfo]:
        """Get all pods in a namespace with their status.

        Args:
            namespace: Kubernetes namespace
            label_selector: Optional label selector to filter pods (e.g., "app=postgres")

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


class KubernetesControllerSync:
    """Synchronous wrapper for KubernetesController.

    Automatically wraps all async methods from the underlying controller
    and exposes them as synchronous methods using run_sync().
    """

    def __init__(self, controller: KubernetesController):
        self._controller = controller

    def __getattr__(self, name: str) -> Any:
        """Dynamically wrap async methods as sync."""
        attr = getattr(self._controller, name)

        # If it's a coroutine function, wrap it
        if callable(attr) and hasattr(attr, "__code__"):
            import inspect

            if inspect.iscoroutinefunction(attr):

                def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                    return run_sync(attr(*args, **kwargs))

                return sync_wrapper

        # Otherwise return as-is (properties, non-async methods)
        return attr


# =============================================================================
# Stub File Generation
# =============================================================================


def generate_sync_stubs() -> str:
    """Generate a .pyi stub file using AST parsing.

    This function automatically extracts dataclass definitions and method signatures
    from the source file using AST parsing, ensuring the stub file stays in perfect
    sync with the implementation without any manual updates.

    Returns:
        The complete content of the .pyi stub file as a string
    """
    import ast
    import inspect
    import re
    from pathlib import Path

    # Read and parse the source file
    source_file = Path(__file__)
    source_code = source_file.read_text()
    tree = ast.parse(source_code)

    # Extract dataclasses
    dataclass_defs = []
    dataclass_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check if it's a dataclass
            has_dataclass_decorator = any(
                (isinstance(d, ast.Name) and d.id == "dataclass")
                or (isinstance(d, ast.Attribute) and d.attr == "dataclass")
                for d in node.decorator_list
            )
            if has_dataclass_decorator:
                dataclass_names.append(node.name)
                # Reconstruct the dataclass definition
                fields = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(
                        item.target, ast.Name
                    ):
                        field_name = item.target.id
                        # Get annotation as string
                        annotation = ast.unparse(item.annotation)
                        # Get default value if present
                        if item.value:
                            default = ast.unparse(item.value)
                            fields.append(f"    {field_name}: {annotation} = {default}")
                        else:
                            fields.append(f"    {field_name}: {annotation}")

                # Get docstring if present
                docstring = ""
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                ):
                    docstring = f'    """{node.body[0].value.value}"""'

                dataclass_def = f"@dataclass\nclass {node.name}:\n"
                if docstring:
                    dataclass_def += f"{docstring}\n"
                dataclass_def += "\n".join(fields) if fields else "    pass"
                dataclass_defs.append(dataclass_def + "\n")

    # Get methods from KubernetesController using inspect
    methods = []
    for name, method in inspect.getmembers(
        KubernetesController, predicate=inspect.isfunction
    ):
        if name.startswith("_"):
            continue

        sig = inspect.signature(method)
        params = []
        seen_keyword_only_separator = False

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            # Add keyword-only separator if this is the first keyword-only param
            if (
                param.kind == inspect.Parameter.KEYWORD_ONLY
                and not seen_keyword_only_separator
            ):
                params.append("*")
                seen_keyword_only_separator = True

            param_str = param_name
            if param.annotation != inspect.Parameter.empty:
                annotation = param.annotation
                if isinstance(annotation, type):
                    annotation = annotation.__name__
                else:
                    annotation = str(annotation).replace("typing.", "")
                param_str += f": {annotation}"

            if param.default != inspect.Parameter.empty:
                if param.default is None:
                    param_str += " = None"
                elif isinstance(param.default, str):
                    param_str += f' = "{param.default}"'
                elif isinstance(param.default, bool):
                    param_str += f" = {param.default}"
                else:
                    param_str += f" = {param.default}"

            params.append(param_str)

        params_str = ", ".join(params)

        return_annotation = sig.return_annotation
        if return_annotation == inspect.Signature.empty:
            return_type = "Any"
        else:
            return_type_str = str(return_annotation)
            match = re.search(r"Coroutine\[Any, Any, (.+)\]", return_type_str)
            if match:
                return_type = match.group(1)
            else:
                return_type = return_type_str.replace("typing.", "")

        method_stub = f"    def {name}(self, {params_str}) -> {return_type}: ..."
        methods.append(method_stub)

    # Build __all__ export list
    all_exports = dataclass_names + ["KubernetesController", "KubernetesControllerSync"]

    # Build async method stubs (for KubernetesController abstract class)
    async_methods = []
    for name, method in inspect.getmembers(
        KubernetesController, predicate=inspect.isfunction
    ):
        if name.startswith("_"):
            continue

        sig = inspect.signature(method)
        params = []
        seen_keyword_only_separator = False

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            # Add keyword-only separator if this is the first keyword-only param
            if (
                param.kind == inspect.Parameter.KEYWORD_ONLY
                and not seen_keyword_only_separator
            ):
                params.append("*")
                seen_keyword_only_separator = True

            param_str = param_name
            if param.annotation != inspect.Parameter.empty:
                annotation = param.annotation
                if isinstance(annotation, type):
                    annotation = annotation.__name__
                else:
                    annotation = str(annotation).replace("typing.", "")
                param_str += f": {annotation}"

            if param.default != inspect.Parameter.empty:
                if param.default is None:
                    param_str += " = None"
                elif isinstance(param.default, str):
                    param_str += f' = "{param.default}"'
                elif isinstance(param.default, bool):
                    param_str += f" = {param.default}"
                else:
                    param_str += f" = {param.default}"

            params.append(param_str)

        params_str = ", ".join(params)

        return_annotation = sig.return_annotation
        if return_annotation == inspect.Signature.empty:
            return_type = "Any"
        else:
            return_type_str = str(return_annotation)
            # Keep the Coroutine wrapper for async methods
            return_type = return_type_str.replace("typing.", "")

        async_method_stub = (
            f"    async def {name}(self, {params_str}) -> {return_type}: ..."
        )
        async_methods.append(async_method_stub)

    # Build the complete stub file content
    stub_content = f'''"""Type stubs for controller module.

This file is AUTO-GENERATED by running:
    python -m src.infra.k8s.controller

Do not edit manually. Regenerate after updating KubernetesController.
Dataclasses are automatically extracted from source using AST parsing.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__all__ = {all_exports!r}


# =============================================================================
# Data Types (AUTO-EXTRACTED)
# =============================================================================

{chr(10).join(dataclass_defs)}


# =============================================================================
# Abstract Controller
# =============================================================================

class KubernetesController(ABC):
    """Abstract base class for Kubernetes operations.

    All methods are async to support both sync (kubectl) and async (kr8s)
    implementations. Use `run_sync()` to call from synchronous code.
    """

{chr(10).join(async_methods)}


# =============================================================================
# Synchronous Wrapper
# =============================================================================

class KubernetesControllerSync:
    """Synchronous wrapper for KubernetesController with full type hints.

    All async methods from KubernetesController are exposed as synchronous methods.
    The underlying async controller is wrapped automatically using run_sync().
    """

    def __init__(self, controller: KubernetesController) -> None:
        """Initialize the synchronous wrapper.

        Args:
            controller: The underlying async KubernetesController instance
        """
        ...

{chr(10).join(methods)}
'''

    return stub_content


if __name__ == "__main__":
    """Generate KubernetesControllerSync stub file."""
    from pathlib import Path

    # Generate stub content
    stub_content = generate_sync_stubs()

    # Write to .pyi file next to this module
    stub_path = Path(__file__).with_suffix(".pyi")
    stub_path.write_text(stub_content)

    print(f"✅ Generated type stubs: {stub_path}")
    print(f"📝 {len(stub_content.splitlines())} lines")
    print("\nTo use the synchronous wrapper with full type hints:")
    print("  from src.infra.k8s.controller import KubernetesControllerSync")
    print("  from src.infra.k8s.kubectl import KubectlController")
    print("")
    print("  sync_controller = KubernetesControllerSync(KubectlController())")
    print("  pods = sync_controller.get_pods('my-namespace')  # Fully typed!")
