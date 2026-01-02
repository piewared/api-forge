"""Helm release management.

This module handles Helm chart deployment, upgrade, and release management
including stuck release cleanup and rollback handling.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from src.cli.deployment.shell_commands import ShellCommands
from src.cli.shared.console import CLIConsole
from src.infra.constants import DeploymentConstants, DeploymentPaths
from src.infra.k8s.controller import KubernetesControllerSync
from src.infra.k8s.helpers import get_k8s_controller_sync
from src.utils.paths import get_project_root

CONTROLLER = get_k8s_controller_sync()


class HelmReleaseManager:
    """Manages Helm releases for Kubernetes deployment.

    Handles:
    - Helm chart deployment via upgrade --install
    - Stuck release cleanup
    - Image override file generation
    - Deployment restart for secret consistency
    - Rollout status monitoring
    """

    def __init__(
        self,
        console: CLIConsole,
        commands: ShellCommands | None = None,
        controller: KubernetesControllerSync = CONTROLLER,
        paths: DeploymentPaths | None = None,
        constants: DeploymentConstants | None = None,
    ) -> None:
        """Initialize the Helm release manager.

        Args:
            commands: Shell command executor
            console: Rich console for output
            paths: Deployment path resolver
            constants: Optional deployment constants
        """
        self._commands = commands or ShellCommands(get_project_root())
        self._console = console
        self._paths = paths or DeploymentPaths(get_project_root())
        self._constants = constants or DeploymentConstants()
        self._controller = controller

    def create_image_override_file(
        self,
        image_tag: str,
        registry: str | None = None,
        ingress_enabled: bool = False,
        ingress_host: str | None = None,
        ingress_tls_secret: str | None = None,
        ingress_tls_auto: bool = False,
        ingress_tls_staging: bool = False,
    ) -> Path:
        """Create a temporary values file to override image tags and ingress.

        Args:
            image_tag: The unique image tag to use for all images
            registry: Optional container registry prefix for remote clusters
            ingress_enabled: Whether to enable Ingress for external access
            ingress_host: Hostname for Ingress (e.g., api.example.com)
            ingress_tls_secret: TLS secret name for HTTPS (manual certificate)
            ingress_tls_auto: Auto-provision TLS via cert-manager
            ingress_tls_staging: Use staging Let's Encrypt (with ingress_tls_auto)

        Returns:
            Path to the temporary override file
        """
        # Determine image repository - use registry prefix for remote clusters
        if registry:
            app_repo = f"{registry}/{self._constants.APP_IMAGE_NAME}"
            postgres_repo = f"{registry}/{self._constants.POSTGRES_IMAGE_NAME}"
            redis_repo = f"{registry}/{self._constants.REDIS_IMAGE_NAME}"
            temporal_repo = f"{registry}/{self._constants.TEMPORAL_IMAGE_NAME}"
        else:
            app_repo = self._constants.APP_IMAGE_NAME
            postgres_repo = self._constants.POSTGRES_IMAGE_NAME
            redis_repo = self._constants.REDIS_IMAGE_NAME
            temporal_repo = self._constants.TEMPORAL_IMAGE_NAME

        override_values: dict[str, Any] = {
            "app": {"image": {"repository": app_repo, "tag": image_tag}},
            "worker": {"image": {"repository": app_repo, "tag": image_tag}},
            # Use content-based tags for infra images to avoid stale image issues
            "postgres": {"image": {"repository": postgres_repo, "tag": image_tag}},
            "redis": {"image": {"repository": redis_repo, "tag": image_tag}},
            "temporal": {"image": {"repository": temporal_repo, "tag": image_tag}},
        }

        # Add ingress configuration if enabled
        if ingress_enabled:
            ingress_config: dict[str, Any] = {"enabled": True}

            # Set hostname if provided
            host = ingress_host or "api.local"
            ingress_config["hosts"] = [
                {"host": host, "paths": [{"path": "/", "pathType": "Prefix"}]}
            ]

            tls_info = ""

            # Handle automatic TLS via cert-manager
            if ingress_tls_auto:
                issuer_name = (
                    "letsencrypt-staging" if ingress_tls_staging else "letsencrypt-prod"
                )
                # Add cert-manager annotation
                ingress_config["annotations"] = {
                    "cert-manager.io/cluster-issuer": issuer_name
                }
                # Generate secret name from hostname (sanitize for K8s naming)
                auto_secret_name = host.replace(".", "-") + "-tls"
                ingress_config["tls"] = [
                    {"secretName": auto_secret_name, "hosts": [host]}
                ]
                tls_info = f" (TLS: auto via {issuer_name})"
            # Add TLS configuration if manual secret is provided
            elif ingress_tls_secret:
                ingress_config["tls"] = [
                    {"secretName": ingress_tls_secret, "hosts": [host]}
                ]
                tls_info = f" (TLS: {ingress_tls_secret})"

            override_values["app"]["ingress"] = ingress_config

            self._console.print(
                f"[bold cyan]🌐 Ingress enabled:[/bold cyan] {host}{tls_info}"
            )

        temp_file = Path(tempfile.mktemp(suffix=".yaml", prefix="helm-image-override-"))
        with open(temp_file, "w") as f:
            yaml.dump(override_values, f, default_flow_style=False)

        self._console.print(f"[dim]Created image override file: {temp_file}[/dim]")
        return temp_file

    def deploy_release(
        self,
        namespace: str,
        image_override_file: Path,
    ) -> None:
        """Deploy resources via Helm upgrade --install.

        Does NOT wait for pods to be ready - that happens after we restart
        all deployments to ensure consistent secrets.

        Args:
            namespace: Target Kubernetes namespace
            image_override_file: Path to values file with image tag overrides
        """
        from .image_builder import DeploymentError

        # Clean up any stuck releases first
        self._cleanup_stuck_release(self._constants.HELM_RELEASE_NAME, namespace)

        self._console.print("[bold cyan]🚀 Deploying resources via Helm...[/bold cyan]")

        def print_helm_output(line: str) -> None:
            """Print Helm output in real-time, filtering noise."""
            line = line.strip()
            if not line:
                return
            # Skip noisy warning lines about table values
            if "warning:" in line.lower() and "table" in line.lower():
                return
            self._console.print(f"  [dim]{line}[/dim]")

        try:
            # Don't use --wait here. We need to restart all deployments first
            # so they pick up fresh secrets before waiting for pods to be ready.
            result = self._commands.helm.upgrade_install(
                release_name=self._constants.HELM_RELEASE_NAME,
                chart_path=self._paths.helm_chart,
                namespace=namespace,
                value_files=[image_override_file]
                if image_override_file.exists()
                else None,
                timeout=self._constants.HELM_TIMEOUT,
                wait=False,
                wait_for_jobs=False,
                on_output=print_helm_output,
            )

            if not result.success:
                self._console.error("Helm deployment failed")
                raise DeploymentError(
                    "Helm deployment failed",
                    details=(
                        "The Helm chart could not be deployed to the cluster.\n\n"
                        "Common causes:\n"
                        "  • Kubernetes cluster is not running or accessible\n"
                        "  • Previous deployment left resources in a bad state\n"
                        "  • Secrets or config files are missing or invalid\n"
                        "  • Insufficient cluster resources (CPU, memory)\n\n"
                        "Recovery steps:\n"
                        "  1. Check cluster status: kubectl cluster-info\n"
                        "  2. Check pod status: kubectl get pods -n api-forge-prod\n"
                        "  3. View pod logs: kubectl logs <pod-name> -n api-forge-prod\n"
                        "  4. Clean up and retry: uv run api-forge-cli deploy down k8s --volumes\n"
                        "  5. Redeploy: uv run api-forge-cli deploy up k8s"
                    ),
                )

        finally:
            # Clean up temporary override file
            if image_override_file.exists():
                image_override_file.unlink()
                self._console.print("[dim]Cleaned up temporary override file[/dim]")

        self._console.ok(f"Helm manifests applied to namespace {namespace}")

    def _cleanup_stuck_release(self, release_name: str, namespace: str) -> None:
        """Clean up Helm release stuck in problematic state.

        Args:
            release_name: Name of the Helm release
            namespace: Target namespace
        """
        stuck_releases = self._commands.helm.get_stuck_releases(namespace, release_name)
        if not stuck_releases:
            return

        for release in stuck_releases:
            self._console.warn(
                f"Found release '{release.name}' in "
                f"'{release.status}' state. Cleaning up..."
            )

            # Try normal uninstall first
            result = self._commands.helm.uninstall(release.name, namespace)
            if result.success:
                self._console.ok(
                    f"Successfully cleaned up stuck release '{release.name}'"
                )
                continue

            # Force cleanup if normal uninstall fails
            self._console.warn("Normal uninstall failed. Attempting force cleanup...")
            self._controller.delete_resources_by_label(
                "all,configmap,secret,pvc",
                namespace,
                f"app.kubernetes.io/instance={release.name}",
                force=True,
            )
            self._controller.delete_helm_secrets(namespace, release.name)
            self._console.ok(f"Force cleaned up release '{release.name}'")

    def restart_all_deployments(self, namespace: str) -> None:
        """Restart all deployments to pick up fresh secrets and configs.

        This ensures all pods use the same version of secrets, configs,
        and images, preventing mixed states.

        Args:
            namespace: Target Kubernetes namespace
        """
        self._console.print(
            "[bold cyan]♻️  Restarting all deployments for consistency...[/bold cyan]"
        )
        result = self._controller.rollout_restart("deployment", namespace)
        if result.success:
            if result.stdout:
                for line in result.stdout.strip().split("\n"):
                    self._console.print(f"  [dim]{line}[/dim]")
            self._console.ok("All deployments restarted successfully")
        else:
            self._console.warn(
                f"Rollout restart may have failed (exit code {result.returncode})"
            )
            if result.stderr:
                self._console.error(f"  {result.stderr}")

    def wait_for_rollouts(self, namespace: str) -> None:
        """Wait for all deployment rollouts to complete.

        Args:
            namespace: Target Kubernetes namespace
        """
        self._console.print(
            "[bold cyan]⏳ Waiting for rollouts to complete...[/bold cyan]"
        )

        deployments = self._controller.get_deployments(namespace)
        if not deployments:
            self._console.warn("No deployments found to wait for")
            return

        failed_deployments = []
        for deployment in deployments:
            with self._console.status(f"[cyan]  Waiting for {deployment}...[/cyan]"):
                result = self._controller.rollout_status(
                    "deployment", namespace, deployment, timeout="3m"
                )
            if result.success:
                self._console.ok(f"  {deployment} ready")
            else:
                self._console.warn(f"  {deployment} timed out")
                failed_deployments.append(deployment)

        if failed_deployments:
            self._console.warn(
                f"Some rollouts timed out: {', '.join(failed_deployments)}"
            )
            self._console.warn(f"💡 Check status with: kubectl get pods -n {namespace}")
            self._console.warn(
                f"💡 To rollback: helm rollback "
                f"{self._constants.HELM_RELEASE_NAME} -n {namespace}"
            )
        else:
            self._console.ok("All rollouts completed successfully")
