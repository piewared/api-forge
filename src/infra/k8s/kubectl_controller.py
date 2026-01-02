"""Kubectl-based implementation of KubernetesController.

Uses subprocess calls to kubectl for all operations.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from .controller import (
    ClusterIssuerStatus,
    CommandResult,
    JobInfo,
    KubernetesController,
    PodInfo,
    ReplicaSetInfo,
    ServiceInfo,
)


class KubectlController(KubernetesController):
    """Kubernetes controller using kubectl subprocess calls.

    All methods are async but internally use asyncio.to_thread()
    to run blocking subprocess calls without blocking the event loop.
    """

    async def _run_kubectl(
        self,
        args: list[str],
        *,
        capture_output: bool = True,
        input_data: str | None = None,
    ) -> CommandResult:
        """Run a kubectl command asynchronously.

        Args:
            args: Command arguments (without 'kubectl' prefix)
            capture_output: Whether to capture stdout/stderr
            input_data: Optional input to send to stdin

        Returns:
            CommandResult with execution results
        """
        import subprocess

        cmd = ["kubectl", *args]

        def _run() -> CommandResult:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                input=input_data,
            )
            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                returncode=result.returncode,
            )

        return await asyncio.to_thread(_run)

    # =========================================================================
    # Cluster Context
    # =========================================================================

    async def get_current_context(self) -> str:
        """Get the current kubectl context name."""
        result = await self._run_kubectl(["config", "current-context"])
        return result.stdout.strip() if result.success else "unknown"

    async def is_minikube_context(self) -> bool:
        """Check if the current kubectl context is Minikube."""
        result = await self._run_kubectl(["config", "current-context"])
        if not result.success:
            return False
        return "minikube" in result.stdout.strip().lower()

    # =========================================================================
    # Namespace Operations
    # =========================================================================

    async def namespace_exists(self, namespace: str) -> bool:
        """Check if a namespace exists."""
        result = await self._run_kubectl(["get", "namespace", namespace])
        return result.success

    async def delete_namespace(
        self,
        namespace: str,
        *,
        wait: bool = True,
        timeout: str = "120s",
    ) -> CommandResult:
        """Delete a Kubernetes namespace and all its resources."""
        args = ["delete", "namespace", namespace]
        if wait:
            args.append("--wait=true")
            args.extend(["--timeout", timeout])
        return await self._run_kubectl(args)

    async def delete_pvcs(self, namespace: str) -> CommandResult:
        """Delete all PersistentVolumeClaims in a namespace."""
        return await self._run_kubectl(["delete", "pvc", "--all", "-n", namespace])

    # =========================================================================
    # Resource Operations
    # =========================================================================

    async def apply_manifest(self, manifest_path: Path) -> CommandResult:
        """Apply a Kubernetes manifest file."""
        return await self._run_kubectl(["apply", "-f", str(manifest_path)])

    async def resource_exists(
        self,
        resource_type: str,
        name: str,
        namespace: str,
    ) -> bool:
        """Check if a Kubernetes resource exists."""
        result = await self._run_kubectl(["get", resource_type, name, "-n", namespace])
        return result.success

    async def delete_resource(
        self,
        resource_type: str,
        name: str,
        namespace: str,
        *,
        cascade: str | None = None,
        wait: bool = True,
    ) -> CommandResult:
        """Delete a specific Kubernetes resource by name."""
        args = ["delete", resource_type, name, "-n", namespace]
        if cascade:
            args.append(f"--cascade={cascade}")
        if wait:
            args.append("--wait=true")
        else:
            args.append("--wait=false")
        return await self._run_kubectl(args)

    async def delete_resources_by_label(
        self,
        resource_types: str,
        namespace: str,
        label_selector: str,
        *,
        force: bool = False,
        cascade: str | None = None,
    ) -> CommandResult:
        """Delete Kubernetes resources matching a label selector."""
        args = [
            "delete",
            resource_types,
            "-n",
            namespace,
            "-l",
            label_selector,
        ]
        if force:
            args.extend(["--force", "--grace-period=0"])
        if cascade:
            args.append(f"--cascade={cascade}")
        return await self._run_kubectl(args)

    async def delete_helm_secrets(
        self,
        namespace: str,
        release_name: str,
    ) -> CommandResult:
        """Delete Helm release metadata secrets."""
        return await self._run_kubectl(
            [
                "delete",
                "secret",
                "-n",
                namespace,
                "-l",
                f"name={release_name},owner=helm",
            ]
        )

    # =========================================================================
    # Deployment Operations
    # =========================================================================

    async def get_deployments(self, namespace: str) -> list[str]:
        """Get list of deployment names in a namespace."""
        result = await self._run_kubectl(
            [
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

    async def rollout_restart(
        self,
        resource_type: str,
        namespace: str,
        name: str | None = None,
    ) -> CommandResult:
        """Trigger a rolling restart of a deployment/daemonset/statefulset."""
        if name:
            args = [
                "rollout",
                "restart",
                resource_type,
                name,
                "-n",
                namespace,
            ]
        else:
            args = ["rollout", "restart", resource_type, "-n", namespace]
        return await self._run_kubectl(args)

    async def rollout_status(
        self,
        resource_type: str,
        namespace: str,
        name: str | None = None,
        *,
        timeout: str = "300s",
    ) -> CommandResult:
        """Wait for a rollout to complete."""
        if name:
            args = [
                "rollout",
                "status",
                resource_type,
                name,
                "-n",
                namespace,
                f"--timeout={timeout}",
            ]
        else:
            args = [
                "rollout",
                "status",
                resource_type,
                "-n",
                namespace,
                f"--timeout={timeout}",
            ]
        return await self._run_kubectl(args, capture_output=False)

    async def get_deployment_revision(
        self,
        name: str,
        namespace: str,
    ) -> str | None:
        """Get the current revision number of a deployment."""
        result = await self._run_kubectl(
            [
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
    # ReplicaSet Operations
    # =========================================================================

    async def get_replicasets(self, namespace: str) -> list[ReplicaSetInfo]:
        """Get all ReplicaSets in a namespace."""
        result = await self._run_kubectl(
            ["get", "replicasets", "-n", namespace, "-o", "json"]
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

    async def delete_replicaset(
        self,
        name: str,
        namespace: str,
    ) -> CommandResult:
        """Delete a specific ReplicaSet."""
        return await self._run_kubectl(["delete", "replicaset", name, "-n", namespace])

    async def scale_replicaset(
        self,
        name: str,
        namespace: str,
        replicas: int,
    ) -> CommandResult:
        """Scale a ReplicaSet to a specific number of replicas."""
        return await self._run_kubectl(
            [
                "scale",
                "replicaset",
                name,
                f"--replicas={replicas}",
                "-n",
                namespace,
            ]
        )

    # =========================================================================
    # Pod Operations
    # =========================================================================

    async def get_pods(
        self,
        namespace: str,
        label_selector: str | None = None,
    ) -> list[PodInfo]:
        """Get all pods in a namespace with their status.

        Args:
            namespace: Kubernetes namespace to search
            label_selector: Optional label selector to filter pods (e.g., "app=postgres")

        Returns:
            List of PodInfo objects matching the criteria
        """
        args = ["get", "pods", "-n", namespace, "-o", "json"]
        if label_selector:
            args.extend(["-l", label_selector])

        result = await self._run_kubectl(args)
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

                pod_status = phase
                restarts = 0

                for cs in container_statuses:
                    restarts += cs.get("restartCount", 0)
                    state = cs.get("state", {})
                    if "waiting" in state:
                        reason = state["waiting"].get("reason", "")
                        if reason:
                            pod_status = reason
                    elif "terminated" in state:
                        reason = state["terminated"].get("reason", "")
                        if reason == "Error":
                            pod_status = "Error"

                pods.append(
                    PodInfo(
                        name=name,
                        status=pod_status,
                        restarts=restarts,
                        creation_timestamp=creation_timestamp,
                        job_owner=job_owner,
                        ip=status.get("podIP", ""),
                        node=spec.get("nodeName", "")
                        if (spec := pod.get("spec"))
                        else "",
                    )
                )

            return pods
        except json.JSONDecodeError:
            return []

    async def wait_for_pods(
        self,
        namespace: str,
        label_selector: str,
        *,
        condition: str = "ready",
        timeout: str = "300s",
    ) -> CommandResult:
        """Wait for pods matching a selector to reach a condition."""
        return await self._run_kubectl(
            [
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
        """Get logs from Kubernetes pods."""
        args = ["logs", "-n", namespace]

        if pod:
            args.append(pod)
        elif label_selector:
            args.extend(["-l", label_selector, "--all-containers=true"])

        if container:
            args.extend(["-c", container])

        if follow:
            args.append("-f")

        args.append(f"--tail={tail}")

        if previous:
            args.append("--previous")

        return await self._run_kubectl(args, capture_output=not follow)

    # =========================================================================
    # Job Operations
    # =========================================================================

    async def get_jobs(self, namespace: str) -> list[JobInfo]:
        """Get all jobs in a namespace with their status."""
        result = await self._run_kubectl(["get", "jobs", "-n", namespace, "-o", "json"])
        if not result.success or not result.stdout:
            return []

        try:
            data = json.loads(result.stdout)
            jobs = []

            for job in data.get("items", []):
                name = job.get("metadata", {}).get("name", "")
                status = job.get("status", {})

                if status.get("succeeded", 0) > 0:
                    job_status = "Complete"
                elif status.get("failed", 0) > 0:
                    job_status = "Failed"
                elif status.get("active", 0) > 0:
                    job_status = "Running"
                else:
                    job_status = "Unknown"

                jobs.append(JobInfo(name=name, status=job_status))

            return jobs
        except json.JSONDecodeError:
            return []

    # =========================================================================
    # Service Operations
    # =========================================================================

    async def get_services(self, namespace: str) -> list[ServiceInfo]:
        """Get all services in a namespace."""
        result = await self._run_kubectl(
            ["get", "services", "-n", namespace, "-o", "json"]
        )
        if not result.success or not result.stdout:
            return []

        try:
            data = json.loads(result.stdout)
            services = []

            for svc in data.get("items", []):
                metadata = svc.get("metadata", {})
                spec = svc.get("spec", {})
                status = svc.get("status", {})

                # Get external IP from LoadBalancer status
                external_ip = ""
                lb_ingress = status.get("loadBalancer", {}).get("ingress", [])
                if lb_ingress:
                    external_ip = lb_ingress[0].get(
                        "ip", lb_ingress[0].get("hostname", "")
                    )

                # Format ports
                ports = []
                for port in spec.get("ports", []):
                    port_str = f"{port.get('port')}"
                    if target := port.get("targetPort"):
                        port_str += f":{target}"
                    if proto := port.get("protocol"):
                        port_str += f"/{proto}"
                    ports.append(port_str)

                services.append(
                    ServiceInfo(
                        name=metadata.get("name", ""),
                        type=spec.get("type", ""),
                        cluster_ip=spec.get("clusterIP", ""),
                        external_ip=external_ip,
                        ports=",".join(ports),
                    )
                )

            return services
        except json.JSONDecodeError:
            return []

    # =========================================================================
    # Cert-Manager Operations
    # =========================================================================

    async def check_cert_manager_installed(self) -> bool:
        """Check if cert-manager is installed in the cluster."""
        result = await self._run_kubectl(
            ["get", "pods", "-n", "cert-manager", "-o", "name"]
        )
        return result.success and bool(result.stdout.strip())

    async def get_cluster_issuer_status(
        self,
        issuer_name: str,
    ) -> ClusterIssuerStatus:
        """Get the status of a cert-manager ClusterIssuer."""
        result = await self._run_kubectl(
            [
                "get",
                "clusterissuer",
                issuer_name,
                "-o",
                "json",
            ]
        )

        if not result.success:
            return ClusterIssuerStatus(
                exists=False,
                ready=False,
                message="ClusterIssuer not found",
            )

        try:
            data = json.loads(result.stdout)
            conditions = data.get("status", {}).get("conditions", [])

            ready = False
            message = ""

            for condition in conditions:
                if condition.get("type") == "Ready":
                    ready = condition.get("status") == "True"
                    message = condition.get("message", "")
                    break

            return ClusterIssuerStatus(
                exists=True,
                ready=ready,
                message=message,
            )
        except json.JSONDecodeError:
            return ClusterIssuerStatus(
                exists=True,
                ready=False,
                message="Failed to parse ClusterIssuer status",
            )

    async def get_cluster_issuer_yaml(self, issuer_name: str) -> str | None:
        """Get the YAML representation of a ClusterIssuer."""
        result = await self._run_kubectl(
            ["get", "clusterissuer", issuer_name, "-o", "yaml"]
        )
        return result.stdout if result.success else None
