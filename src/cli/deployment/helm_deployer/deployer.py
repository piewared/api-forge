"""Kubernetes environment deployer using Helm.

This module provides the HelmDeployer class which orchestrates Kubernetes
deployments via Helm. It coordinates specialized components for:
- Docker image building and loading
- Secret management
- Configuration synchronization
- Helm chart deployment
- Post-deployment cleanup

The deployer automatically detects the target cluster type and uses the
appropriate image loading strategy (Minikube, Kind, or remote registry).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from ..base import BaseDeployer
from ..health_checks import HealthChecker
from ..shell_commands import ShellCommands
from ..status_display import StatusDisplay
from .cleanup import CleanupManager
from .config_sync import ConfigSynchronizer
from .constants import DeploymentConstants, DeploymentPaths
from .helm_release import HelmReleaseManager
from .image_builder import DeploymentError, ImageBuilder
from .secret_manager import SecretManager

# Re-export for backward compatibility
__all__ = ["HelmDeployer", "DeploymentError"]


class HelmDeployer(BaseDeployer):
    """Deployer for Kubernetes environment using Helm.

    This class orchestrates the complete Kubernetes deployment workflow,
    delegating to specialized components for each phase of deployment.

    The deployment workflow consists of:
    1. Build and tag Docker images with content-based tags
    2. Load images into target cluster (auto-detected)
    3. Generate and deploy Kubernetes secrets
    4. Sync configuration between config.yaml and values.yaml
    5. Copy config files to Helm staging area
    6. Deploy via Helm upgrade --install
    7. Restart deployments for secret consistency
    8. Wait for rollouts to complete
    9. Clean up old ReplicaSets

    Attributes:
        constants: Deployment configuration constants
        paths: Deployment path resolver
        commands: Shell command executor
        image_builder: Docker image builder
        secret_manager: Secret deployment handler
        config_sync: Configuration synchronizer
        helm_release: Helm release manager
        cleanup: Post-deployment cleanup manager
    """

    def __init__(self, console: Console, project_root: Path):
        """Initialize the Kubernetes deployer.

        Args:
            console: Rich console for output
            project_root: Path to the project root directory
        """
        super().__init__(console, project_root)

        # Core configuration
        self.constants = DeploymentConstants()
        self.paths = DeploymentPaths(project_root)

        # UI components
        self.status_display = StatusDisplay(console)
        self.health_checker = HealthChecker()

        # Command executor
        self.commands = ShellCommands(project_root)

        # Initialize specialized components
        self.image_builder = ImageBuilder(
            commands=self.commands,
            console=console,
            project_root=project_root,
            constants=self.constants,
        )
        self.secret_manager = SecretManager(
            commands=self.commands,
            console=console,
            paths=self.paths,
        )
        self.config_sync = ConfigSynchronizer(
            console=console,
            paths=self.paths,
        )
        self.helm_release = HelmReleaseManager(
            commands=self.commands,
            console=console,
            paths=self.paths,
            constants=self.constants,
        )
        self.cleanup = CleanupManager(
            commands=self.commands,
            console=console,
            constants=self.constants,
        )

        # Import validator here to avoid circular imports
        from .validator import DeploymentValidator

        self.validator = DeploymentValidator(
            commands=self.commands,
            console=console,
            constants=self.constants,
        )

    # =========================================================================
    # Progress Factory
    # =========================================================================

    def _create_progress(self) -> Progress:
        """Create a Rich Progress instance for progress bars."""
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True,
        )

    # =========================================================================
    # Validation
    # =========================================================================

    def _validate_registry_url(self, registry: str) -> None:
        """Validate the format of a container registry URL.

        Args:
            registry: Registry URL to validate

        Raises:
            DeploymentError: If the registry URL format is invalid
        """
        if not self.constants.REGISTRY_PATTERN.match(registry):
            raise DeploymentError(
                f"Invalid registry URL format: '{registry}'",
                details="Expected format: host.domain/path or host:port/path\n"
                "Examples:\n"
                "  - ghcr.io/myuser\n"
                "  - docker.io/mycompany\n"
                "  - registry.example.com:5000/project",
            )

    # =========================================================================
    # Public Interface
    # =========================================================================

    def deploy(
        self,
        namespace: str | None = None,
        registry: str | None = None,
        ingress_enabled: bool = False,
        ingress_host: str | None = None,
        ingress_tls_secret: str | None = None,
        ingress_tls_auto: bool = False,
        ingress_tls_staging: bool = False,
        **kwargs: Any,
    ) -> None:
        """Deploy to Kubernetes cluster.

        Deployment workflow:
        1. Build Docker images with content-based tagging
        2. Load images into target cluster (auto-detected)
        3. Generate and deploy secrets
        4. Sync config.yaml settings to values.yaml
        5. Copy config files to Helm staging area
        6. Deploy resources via Helm
        7. Restart deployments for consistency
        8. Wait for rollouts
        9. Clean up old resources

        Args:
            namespace: Kubernetes namespace (default: api-forge-prod)
            registry: Container registry for remote clusters
            ingress_enabled: Whether to enable Ingress for external access
            ingress_host: Hostname for Ingress (e.g., api.example.com)
            ingress_tls_secret: TLS secret name for HTTPS (manual)
            ingress_tls_auto: Auto-provision TLS via cert-manager
            ingress_tls_staging: Use staging Let's Encrypt (with ingress_tls_auto)
            **kwargs: Reserved for future options
        """
        if not self.check_env_file():
            return

        namespace = namespace or self.constants.DEFAULT_NAMESPACE

        # Validate registry URL format if provided
        if registry:
            self._validate_registry_url(registry)

        # Phase 0: Pre-deployment validation
        # Check for existing issues that could cause deployment problems
        validation_result = self.validator.validate(namespace)
        self.validator.display_results(validation_result, namespace)

        # If there are issues, prompt for cleanup
        if not validation_result.is_clean:
            if validation_result.requires_cleanup:
                # Critical issues - need cleanup before proceeding
                if self.validator.prompt_cleanup(validation_result, namespace):
                    # User accepted cleanup, execute it
                    if self.validator.run_cleanup(namespace):
                        self.console.print(
                            "[bold green]✓[/bold green] Pre-deployment cleanup completed"
                        )
                    else:
                        # Cleanup failed, abort deployment
                        return
                else:
                    # User declined cleanup for critical issues, abort
                    self.console.print(
                        "[yellow]⚠[/yellow] Deployment cancelled due to unresolved "
                        "critical issues."
                    )
                    return
            else:
                # Non-critical issues - prompt but allow proceeding
                if not self.validator.prompt_cleanup(validation_result, namespace):
                    # User explicitly declined after errors/warnings - respect that
                    return

        # Phase 1: Build and prepare images
        image_tag = self.image_builder.build_and_tag_images(
            progress_factory=self._get_progress_class(),
            registry=registry,
        )

        # Phase 2: Deploy secrets
        self.secret_manager.deploy_secrets(
            namespace=namespace,
            progress_factory=self._get_progress_class(),
        )

        # Phase 3: Prepare configuration
        self.config_sync.sync_config_to_values()
        self.config_sync.copy_config_files(
            progress_factory=self._get_progress_class(),
        )

        # Phase 4: Deploy via Helm
        image_override_file = self.helm_release.create_image_override_file(
            image_tag,
            registry,
            ingress_enabled=ingress_enabled,
            ingress_host=ingress_host,
            ingress_tls_secret=ingress_tls_secret,
            ingress_tls_auto=ingress_tls_auto,
            ingress_tls_staging=ingress_tls_staging,
        )
        self.helm_release.deploy_release(namespace, image_override_file)

        # Phase 5: Restart all deployments for secret consistency
        self.helm_release.restart_all_deployments(namespace)

        # Phase 6: Wait for all pods to be ready
        self.helm_release.wait_for_rollouts(namespace)

        # Phase 7: Cleanup old resources
        self.cleanup.scale_down_old_replicasets(namespace)
        self.cleanup.cleanup_old_replicasets(namespace)

        # Display final status
        self._show_deployment_success(namespace)

    def _get_progress_class(self) -> type[Progress]:
        """Get the Progress class for creating progress bars.

        Returns a class that can be instantiated to create progress bars.
        This allows components to create their own progress instances.
        """
        return Progress

    def teardown(self, namespace: str | None = None, **kwargs: Any) -> None:
        """Remove Kubernetes deployment.

        Args:
            namespace: Kubernetes namespace (default: api-forge-prod)
            **kwargs: Reserved for future options
        """
        namespace = namespace or self.constants.DEFAULT_NAMESPACE

        self.console.print(
            f"[bold red]Uninstalling Helm release from {namespace}...[/bold red]"
        )

        self.commands.helm.uninstall(self.constants.HELM_RELEASE_NAME, namespace)

        with self.console.status(f"[bold red]Deleting namespace {namespace}..."):
            self.commands.kubectl.delete_namespace(namespace, timeout="120s")

        self.success(f"Teardown complete for {namespace}")

    def show_status(self, namespace: str | None = None) -> None:
        """Display the current status of the Kubernetes deployment.

        Args:
            namespace: Kubernetes namespace to check (default: api-forge-prod)
        """
        if namespace is None:
            namespace = self.constants.DEFAULT_NAMESPACE
        self.status_display.show_k8s_status(namespace)

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _show_deployment_success(self, namespace: str) -> None:
        """Display deployment success message and status.

        Args:
            namespace: Target Kubernetes namespace
        """
        self.console.print(
            "\n[bold green]🎉 Kubernetes deployment complete![/bold green]"
        )
        self.status_display.show_k8s_status(namespace)
