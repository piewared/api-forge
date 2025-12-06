"""Kr8s-based implementation of KubernetesController.

Uses the kr8s library for native async Kubernetes operations.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import kr8s
from kr8s.asyncio.objects import (
    Deployment,
    Job,
    Namespace,
    PersistentVolumeClaim,
    Pod,
    ReplicaSet,
    Secret,
    Service,
)

from .controller import (
    ClusterIssuerStatus,
    CommandResult,
    JobInfo,
    KubernetesController,
    PodInfo,
    ReplicaSetInfo,
    ServiceInfo,
)


class Kr8sController(KubernetesController):
    """Kubernetes controller using kr8s library.

    All methods are natively async, leveraging kr8s's async API.

    Note: The kr8s API client is NOT cached because it's tied to the event loop
    that was running when created. When using run_sync() which calls asyncio.run(),
    each call creates a new event loop, making the cached API unusable.
    """

    def __init__(self) -> None:
        """Initialize the kr8s controller."""
        # Note: We don't cache the API because kr8s clients are tied to
        # the event loop they were created in. Since run_sync() uses
        # asyncio.run() which creates/closes event loops, we need a fresh
        # API client each time.
        pass

    async def _get_api(self) -> Any:  # Returns kr8s._api.Api
        """Get or create the kr8s API client.

        Creates a new API client each call because kr8s clients are bound
        to the event loop they were created in.
        """
        return await kr8s.asyncio.api()

    # =========================================================================
    # Cluster Context
    # =========================================================================

    async def get_current_context(self) -> str:
        """Get the current kubectl context name."""
        try:
            api = await self._get_api()
            # Access context via auth object
            return api.auth.active_context or "unknown"
        except Exception:
            return "unknown"

    async def is_minikube_context(self) -> bool:
        """Check if the current kubectl context is Minikube."""
        context = await self.get_current_context()
        return "minikube" in context.lower()

    # =========================================================================
    # Namespace Operations
    # =========================================================================

    async def namespace_exists(self, namespace: str) -> bool:
        """Check if a namespace exists."""
        try:
            api = await self._get_api()
            ns = await Namespace.get(namespace, api=api)
            return ns is not None
        except kr8s.NotFoundError:
            return False
        except Exception:
            return False

    async def delete_namespace(
        self,
        namespace: str,
        *,
        wait: bool = True,
        timeout: str = "120s",
    ) -> CommandResult:
        """Delete a Kubernetes namespace and all its resources."""
        try:
            api = await self._get_api()
            ns = await Namespace.get(namespace, api=api)
            await ns.delete()

            if wait:
                # Parse timeout
                timeout_seconds = self._parse_timeout(timeout)
                try:
                    await asyncio.wait_for(
                        self._wait_for_namespace_deletion(namespace),
                        timeout=timeout_seconds,
                    )
                except TimeoutError:
                    return CommandResult(
                        success=False,
                        stderr=f"Timeout waiting for namespace {namespace} deletion",
                        returncode=1,
                    )

            return CommandResult(
                success=True, stdout=f'namespace "{namespace}" deleted'
            )
        except kr8s.NotFoundError:
            return CommandResult(
                success=False,
                stderr=f'namespace "{namespace}" not found',
                returncode=1,
            )
        except Exception as e:
            return CommandResult(success=False, stderr=str(e), returncode=1)

    async def _wait_for_namespace_deletion(self, namespace: str) -> None:
        """Wait until a namespace no longer exists."""
        while await self.namespace_exists(namespace):
            await asyncio.sleep(1)

    async def delete_pvcs(self, namespace: str) -> CommandResult:
        """Delete all PersistentVolumeClaims in a namespace."""
        try:
            api = await self._get_api()
            deleted = []
            async for pvc in PersistentVolumeClaim.list(namespace=namespace, api=api):
                await pvc.delete()
                deleted.append(pvc.name)
            return CommandResult(
                success=True,
                stdout=f"Deleted PVCs: {', '.join(deleted)}"
                if deleted
                else "No PVCs found",
            )
        except Exception as e:
            return CommandResult(success=False, stderr=str(e), returncode=1)

    # =========================================================================
    # Resource Operations
    # =========================================================================

    async def apply_manifest(self, manifest_path: Path) -> CommandResult:
        """Apply a Kubernetes manifest file.

        Note: kr8s doesn't have a direct 'apply' equivalent, so we use
        kubectl subprocess for this operation.
        """
        import subprocess

        def _run() -> CommandResult:
            result = subprocess.run(
                ["kubectl", "apply", "-f", str(manifest_path)],
                capture_output=True,
                text=True,
            )
            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                returncode=result.returncode,
            )

        return await asyncio.to_thread(_run)

    async def delete_resources_by_label(
        self,
        resource_types: str,
        namespace: str,
        label_selector: str,
        *,
        force: bool = False,
    ) -> CommandResult:
        """Delete Kubernetes resources matching a label selector.

        Note: Uses kubectl for complex multi-resource deletion.
        """
        import subprocess

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

        def _run() -> CommandResult:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                returncode=result.returncode,
            )

        return await asyncio.to_thread(_run)

    async def delete_helm_secrets(
        self,
        namespace: str,
        release_name: str,
    ) -> CommandResult:
        """Delete Helm release metadata secrets."""
        try:
            api = await self._get_api()
            deleted = []
            async for secret in Secret.list(
                namespace=namespace,
                label_selector=f"name={release_name},owner=helm",
                api=api,
            ):
                await secret.delete()
                deleted.append(secret.name)
            return CommandResult(
                success=True,
                stdout=f"Deleted secrets: {', '.join(deleted)}"
                if deleted
                else "No secrets found",
            )
        except Exception as e:
            return CommandResult(success=False, stderr=str(e), returncode=1)

    # =========================================================================
    # Deployment Operations
    # =========================================================================

    async def get_deployments(self, namespace: str) -> list[str]:
        """Get list of deployment names in a namespace."""
        try:
            api = await self._get_api()
            return [d.name async for d in Deployment.list(namespace=namespace, api=api)]
        except Exception:
            return []

    async def rollout_restart(
        self,
        resource_type: str,
        namespace: str,
        name: str | None = None,
    ) -> CommandResult:
        """Trigger a rolling restart of a deployment/daemonset/statefulset.

        Note: kr8s doesn't have a direct rollout restart, using kubectl.
        """
        import subprocess

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

        def _run() -> CommandResult:
            result = subprocess.run(cmd, capture_output=True, text=True)
            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                returncode=result.returncode,
            )

        return await asyncio.to_thread(_run)

    async def rollout_status(
        self,
        resource_type: str,
        namespace: str,
        name: str | None = None,
        *,
        timeout: str = "300s",
    ) -> CommandResult:
        """Wait for a rollout to complete.

        Note: Uses kubectl for streaming status output.
        """
        import subprocess

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

        def _run() -> CommandResult:
            result = subprocess.run(cmd, capture_output=False, text=True)
            return CommandResult(
                success=result.returncode == 0,
                returncode=result.returncode,
            )

        return await asyncio.to_thread(_run)

    async def get_deployment_revision(
        self,
        name: str,
        namespace: str,
    ) -> str | None:
        """Get the current revision number of a deployment."""
        try:
            api = await self._get_api()
            deployment = await Deployment.get(name, namespace=namespace, api=api)
            annotations = deployment.metadata.get("annotations", {})
            revision: str | None = annotations.get("deployment.kubernetes.io/revision")
            return revision
        except Exception:
            return None

    # =========================================================================
    # ReplicaSet Operations
    # =========================================================================

    async def get_replicasets(self, namespace: str) -> list[ReplicaSetInfo]:
        """Get all ReplicaSets in a namespace."""
        try:
            api = await self._get_api()
            result = []

            async for rs in ReplicaSet.list(namespace=namespace, api=api):
                metadata = rs.metadata
                spec = rs.spec
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

                result.append(
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

            return result
        except Exception:
            return []

    async def delete_replicaset(
        self,
        name: str,
        namespace: str,
    ) -> CommandResult:
        """Delete a specific ReplicaSet."""
        try:
            api = await self._get_api()
            rs = await ReplicaSet.get(name, namespace=namespace, api=api)
            await rs.delete()
            return CommandResult(success=True, stdout=f'replicaset "{name}" deleted')
        except kr8s.NotFoundError:
            return CommandResult(
                success=False,
                stderr=f'replicaset "{name}" not found',
                returncode=1,
            )
        except Exception as e:
            return CommandResult(success=False, stderr=str(e), returncode=1)

    async def scale_replicaset(
        self,
        name: str,
        namespace: str,
        replicas: int,
    ) -> CommandResult:
        """Scale a ReplicaSet to a specific number of replicas."""
        try:
            api = await self._get_api()
            rs = await ReplicaSet.get(name, namespace=namespace, api=api)
            await rs.scale(replicas)
            return CommandResult(
                success=True,
                stdout=f"replicaset/{name} scaled to {replicas}",
            )
        except Exception as e:
            return CommandResult(success=False, stderr=str(e), returncode=1)

    # =========================================================================
    # Pod Operations
    # =========================================================================

    async def get_pods(self, namespace: str) -> list[PodInfo]:
        """Get all pods in a namespace with their status."""
        try:
            api = await self._get_api()
            result = []

            async for pod in Pod.list(namespace=namespace, api=api):
                metadata = pod.metadata
                spec = pod.spec
                status = pod.status

                name = metadata.get("name", "")
                creation_timestamp = metadata.get("creationTimestamp", "")

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

                result.append(
                    PodInfo(
                        name=name,
                        status=pod_status,
                        restarts=restarts,
                        creation_timestamp=creation_timestamp,
                        job_owner=job_owner,
                        ip=status.get("podIP", ""),
                        node=spec.get("nodeName", ""),
                    )
                )

            return result
        except Exception:
            return []

    async def wait_for_pods(
        self,
        namespace: str,
        label_selector: str,
        *,
        condition: str = "ready",
        timeout: str = "300s",
    ) -> CommandResult:
        """Wait for pods matching a selector to reach a condition.

        Note: Uses kubectl for the wait operation.
        """
        import subprocess

        cmd = [
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
        ]

        def _run() -> CommandResult:
            result = subprocess.run(cmd, capture_output=False, text=True)
            return CommandResult(
                success=result.returncode == 0,
                returncode=result.returncode,
            )

        return await asyncio.to_thread(_run)

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

        Note: Uses kubectl for log streaming support.
        """
        import subprocess

        cmd = ["kubectl", "logs", "-n", namespace]

        if pod:
            cmd.append(pod)
        elif label_selector:
            cmd.extend(["-l", label_selector, "--all-containers=true"])

        if container:
            cmd.extend(["-c", container])

        if follow:
            cmd.append("-f")

        cmd.append(f"--tail={tail}")

        if previous:
            cmd.append("--previous")

        def _run() -> CommandResult:
            result = subprocess.run(
                cmd,
                capture_output=not follow,
                text=True,
            )
            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout or "" if not follow else "",
                stderr=result.stderr or "" if not follow else "",
                returncode=result.returncode,
            )

        return await asyncio.to_thread(_run)

    # =========================================================================
    # Job Operations
    # =========================================================================

    async def get_jobs(self, namespace: str) -> list[JobInfo]:
        """Get all jobs in a namespace with their status."""
        try:
            api = await self._get_api()
            result = []

            async for job in Job.list(namespace=namespace, api=api):
                name = job.metadata.get("name", "")
                status = job.status

                if status.get("succeeded", 0) > 0:
                    job_status = "Complete"
                elif status.get("failed", 0) > 0:
                    job_status = "Failed"
                elif status.get("active", 0) > 0:
                    job_status = "Running"
                else:
                    job_status = "Unknown"

                result.append(JobInfo(name=name, status=job_status))

            return result
        except Exception:
            return []

    # =========================================================================
    # Service Operations
    # =========================================================================

    async def get_services(self, namespace: str) -> list[ServiceInfo]:
        """Get all services in a namespace."""
        try:
            api = await self._get_api()
            result = []

            async for svc in Service.list(namespace=namespace, api=api):
                metadata = svc.metadata
                spec = svc.spec
                status = svc.status

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

                result.append(
                    ServiceInfo(
                        name=metadata.get("name", ""),
                        type=spec.get("type", ""),
                        cluster_ip=spec.get("clusterIP", ""),
                        external_ip=external_ip,
                        ports=",".join(ports),
                    )
                )

            return result
        except Exception:
            return []

    # =========================================================================
    # Cert-Manager Operations
    # =========================================================================

    async def check_cert_manager_installed(self) -> bool:
        """Check if cert-manager is installed in the cluster."""
        try:
            api = await self._get_api()
            pods = [pod async for pod in Pod.list(namespace="cert-manager", api=api)]
            return len(pods) > 0
        except Exception:
            return False

    async def get_cluster_issuer_status(
        self,
        issuer_name: str,
    ) -> ClusterIssuerStatus:
        """Get the status of a cert-manager ClusterIssuer.

        Note: Uses kubectl as ClusterIssuer is a CRD.
        """
        import subprocess

        def _run() -> ClusterIssuerStatus:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "clusterissuer",
                    issuer_name,
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return ClusterIssuerStatus(
                    exists=False,
                    ready=False,
                    message="ClusterIssuer not found",
                )

            try:
                import json

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
            except Exception:
                return ClusterIssuerStatus(
                    exists=True,
                    ready=False,
                    message="Failed to parse ClusterIssuer status",
                )

        return await asyncio.to_thread(_run)

    async def get_cluster_issuer_yaml(self, issuer_name: str) -> str | None:
        """Get the YAML representation of a ClusterIssuer.

        Note: Uses kubectl as ClusterIssuer is a CRD.
        """
        import subprocess

        def _run() -> str | None:
            result = subprocess.run(
                ["kubectl", "get", "clusterissuer", issuer_name, "-o", "yaml"],
                capture_output=True,
                text=True,
            )
            return result.stdout if result.returncode == 0 else None

        return await asyncio.to_thread(_run)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _parse_timeout(self, timeout: str) -> float:
        """Parse a timeout string like '120s' or '5m' to seconds."""
        if timeout.endswith("s"):
            return float(timeout[:-1])
        elif timeout.endswith("m"):
            return float(timeout[:-1]) * 60
        elif timeout.endswith("h"):
            return float(timeout[:-1]) * 3600
        else:
            return float(timeout)
