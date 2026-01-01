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

from typing import Any

from rich.progress import Progress, SpinnerColumn, TextColumn

from src.cli.shared.console import CLIConsole, console
from src.infra.constants import (
    DEFAULT_CONSTANTS,
    DEFAULT_PATHS,
    DeploymentConstants,
    DeploymentPaths,
)
from src.infra.k8s.controller import KubernetesControllerSync
from src.infra.k8s.helpers import get_k8s_controller_sync
from src.infra.k8s.port_forward import postgres_port_forward
from src.utils.paths import get_project_root

from ..base import BaseDeployer
from ..health_checks import HealthChecker
from ..shell_commands import ShellCommands
from ..status_display import StatusDisplay
from .cleanup import CleanupManager
from .config_sync import ConfigSynchronizer
from .helm_release import HelmReleaseManager
from .image_builder import DeploymentError, ImageBuilder
from .secret_manager import SecretManager

# Re-export for backward compatibility
__all__ = ["HelmDeployer", "DeploymentError"]


CONTROLLER = get_k8s_controller_sync()


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

    def __init__(
        self,
        console: CLIConsole,
        controller: KubernetesControllerSync = CONTROLLER,
        paths: DeploymentPaths | None = None,
        constants: DeploymentConstants | None = None,
    ) -> None:
        """Initialize the Kubernetes deployer.

        Args:
            console: Rich console for output
            project_root: Path to the project root directory
        """
        project_root = get_project_root()
        super().__init__(console, project_root)
        self._controller = controller

        # Core configuration
        self.constants = constants or DeploymentConstants()
        self.paths = paths or DeploymentPaths(project_root)

        # UI components
        self.status_display = StatusDisplay(console)
        self.health_checker = HealthChecker()

        # Command executor
        self.commands = ShellCommands(project_root)

        # Initialize specialized components
        self.image_builder = ImageBuilder(
            commands=self.commands,
            console=console,
            paths=self.paths,
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
            console=console,
            controller=self._controller,
            paths=self.paths,
            constants=self.constants,
        )
        self.cleanup = CleanupManager(
            console=console,
            controller=self._controller,
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
            console=self.console.console,
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
        skip_db_check: bool = False,
        **kwargs: Any,
    ) -> None:
        """Deploy to Kubernetes cluster.

        Deployment workflow:
        1. Build Docker images with content-based tagging
        2. Load images into target cluster (auto-detected)
        3. Deploy secrets
        4. Restart postgres StatefulSet (if bundled postgres enabled)
        5. Verify database accessible (unless skip_db_check)
        6. Sync config.yaml settings to values.yaml
        7. Copy config files to Helm staging area
        8. Deploy resources via Helm
        9. Restart deployments for consistency
        10. Wait for rollouts
        11. Clean up old resources

        Args:
            namespace: Kubernetes namespace (default: api-forge-prod)
            registry: Container registry for remote clusters
            ingress_enabled: Whether to enable Ingress for external access
            ingress_host: Hostname for Ingress (e.g., api.example.com)
            ingress_tls_secret: TLS secret name for HTTPS (manual)
            ingress_tls_auto: Auto-provision TLS via cert-manager
            ingress_tls_staging: Use staging Let's Encrypt (with ingress_tls_auto)
            skip_db_check: Skip database verification before deployment
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

        # Phase 2.5: Restart postgres to pick up new secrets (if bundled postgres)
        self._restart_postgres_if_needed(namespace)

        # Phase 2.6: Verify database is accessible after secret deployment
        if not skip_db_check:
            self._verify_database_or_exit(namespace)

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
            self._controller.delete_namespace(namespace, timeout="120s")

        self.success(f"Teardown complete for {namespace}")

    def show_status(self, namespace: str | None = None) -> None:
        """Display the current status of the Kubernetes deployment.

        Args:
            namespace: Kubernetes namespace to check (default: api-forge-prod)
        """
        if namespace is None:
            namespace = self.constants.DEFAULT_NAMESPACE
        self.status_display.show_k8s_status(namespace)

    def deploy_secrets(self, namespace: str | None = None) -> bool:
        """Deploy Kubernetes secrets to the target namespace.

        Generates secrets if needed (first-time setup) and deploys them
        to the specified Kubernetes namespace.

        Args:
            namespace: Target Kubernetes namespace (default: api-forge-prod)

        Returns:
            True if secrets were deployed successfully
        """
        namespace = namespace or self.constants.DEFAULT_NAMESPACE
        self.secret_manager.deploy_secrets(
            namespace=namespace,
            progress_factory=self._get_progress_class(),
        )
        return True

    def restart_resource(
        self,
        label: str,
        resource_type: str = "statefulset",
        timeout: int = 300,
    ) -> bool:
        """Restart a Kubernetes resource and wait for it to be ready.

        Performs a rollout restart on the specified resource and blocks
        until the rollout is complete and pods are ready.

        Args:
            label: Resource name (e.g., 'postgres', 'app')
            resource_type: Type of resource ('statefulset', 'deployment')
            timeout: Maximum time to wait for rollout (e.g., '300s')

        Returns:
            True if restart succeeded and resource is ready, False otherwise
        """
        namespace = self.constants.DEFAULT_NAMESPACE

        self.console.print(
            f"[bold cyan]♻️  Restarting {resource_type}/{label}...[/bold cyan]"
        )

        # Trigger the rollout restart
        restart_result = self._controller.rollout_restart(
            resource_type=resource_type,
            namespace=namespace,
            name=label,
        )

        if not restart_result.success:
            self.console.print(
                f"[red]Failed to restart {label}: {restart_result.stderr}[/red]"
            )
            return False

        self.console.print(f"[green]✓ {label} restart initiated[/green]")

        # Wait for the rollout to complete
        self.console.print(f"[dim]Waiting for {label} to be ready...[/dim]")

        wait_result = self._controller.rollout_status(
            resource_type=resource_type,
            namespace=namespace,
            name=label,
            timeout=f"{timeout}s",
        )

        if wait_result.success:
            self.console.print(f"[green]✓ {label} is ready[/green]")
            return True
        else:
            self.console.print(
                f"[red]Timeout waiting for {label} to be ready: {wait_result.stderr}[/red]"
            )
            return False

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _get_progress_class(self) -> type[Progress]:
        """Get the Progress class for creating progress bars.

        Returns a class that can be instantiated to create progress bars.
        This allows components to create their own progress instances.
        """
        return Progress

    def _show_deployment_success(self, namespace: str) -> None:
        """Display deployment success message and status.

        Args:
            namespace: Target Kubernetes namespace
        """
        self.console.print(
            "\n[bold green]🎉 Kubernetes deployment complete![/bold green]"
        )
        self.status_display.show_k8s_status(namespace)

    def _restart_postgres_if_needed(self, namespace: str) -> None:
        """Restart postgres StatefulSet if it exists (for secret rotation).

        When secrets are rotated, the postgres pod needs to restart to pick up
        new credentials and sync them to the database via the entrypoint script.

        Args:
            namespace: Kubernetes namespace
        """
        from src.infra.utils.service_config import is_bundled_postgres_enabled

        # Only restart if bundled postgres is enabled
        if not is_bundled_postgres_enabled():
            return

        self.console.print(
            "[bold cyan]♻️  Restarting postgres for secret sync...[/bold cyan]"
        )

        # Try to restart the StatefulSet (will fail gracefully if it doesn't exist)
        restart_result = self._controller.rollout_restart(
            "statefulset", namespace, self.constants.POSTGRES_RESOURCE_NAME
        )

        if restart_result.success:
            self.console.print("[green]✓ Postgres restart triggered[/green]")

            # Wait for postgres to be ready
            self.console.print("[dim]Waiting for postgres to be ready...[/dim]")
            wait_result = self._controller.wait_for_pods(
                namespace=namespace,
                label_selector="app.kubernetes.io/name=postgres",
                condition="ready",
                timeout="300s",
            )

            if wait_result.success:
                self.console.print("[green]✓ Postgres is ready[/green]")
                # Wait additional time for password sync script to complete
                # The postgres entrypoint syncs passwords AFTER postgres starts accepting connections
                import time

                self.console.print(
                    "[dim]Waiting for password sync to complete (15s)...[/dim]"
                )
                time.sleep(15)
            else:
                self.console.print(
                    "[yellow]⚠ Postgres may not be fully ready yet[/yellow]"
                )
        else:
            # StatefulSet doesn't exist or restart failed
            # This is expected on first deployment before postgres is created
            if "not found" in restart_result.stderr.lower():
                self.console.print(
                    "[dim]  ℹ Postgres StatefulSet not found (will be created during deployment)[/dim]"
                )
            else:
                self.console.print(
                    f"[yellow]⚠ Postgres restart failed: {restart_result.stderr}[/yellow]"
                )

    def _verify_database_or_exit(self, namespace: str) -> None:
        """Verify database is accessible or exit deployment.

        Uses port-forward to connect to the database and verify it's accessible.
        Retries with exponential backoff to allow time for password sync after restart.
        If verification fails after all retries, raises SystemExit to abort the deployment.

        Skips verification if postgres pod doesn't exist yet (first deployment).

        Args:
            namespace: Kubernetes namespace

        Raises:
            SystemExit: If database verification fails
        """
        import time

        from src.infra.k8s import get_postgres_label
        from src.infra.postgres.connection import get_settings
        from src.infra.utils.service_config import is_bundled_postgres_enabled

        # Check if postgres pod exists first
        postgres_label = get_postgres_label()
        check_result = self._controller.wait_for_pods(
            namespace=namespace,
            label_selector=postgres_label,
            condition="ready",
            timeout="1s",  # Just checking if it exists, not actually waiting
        )

        if not check_result.success:
            # Postgres doesn't exist yet - this is a first deployment
            self.console.print(
                "[dim]ℹ️  Skipping database verification (postgres not yet deployed)[/dim]"
            )
            return

        self.console.print(
            "[bold cyan]🔍 Verifying database accessibility...[/bold cyan]"
        )

        max_retries = 10
        retry_delay = 5  # seconds

        def verify() -> bool:
            for attempt in range(1, max_retries + 1):
                try:
                    # Clear the settings cache to ensure fresh password values
                    # after secret rotation/deployment
                    get_settings.cache_clear()
                    settings = get_settings()

                    # Import here to avoid circular dependencies
                    from src.infra.k8s.postgres_connection import (
                        get_k8s_postgres_connection,
                    )

                    with postgres_port_forward(
                        namespace=namespace, pod_label=postgres_label
                    ):
                        conn = get_k8s_postgres_connection(settings)
                        success, msg = conn.test_connection()

                    if success:
                        self.console.print(
                            f"[green]✅ Database accessible: {msg[:60]}...[/green]"
                        )
                        return True
                    else:
                        if attempt < max_retries:
                            self.console.print(
                                f"[yellow]⚠ Attempt {attempt}/{max_retries} failed, "
                                f"retrying in {retry_delay}s (password sync may still be in progress)...[/yellow]"
                            )
                            time.sleep(retry_delay)
                        else:
                            self.console.print(
                                f"[red]❌ Database check failed after {max_retries} attempts: {msg}[/red]"
                            )
                            return False

                except ImportError:
                    # psycopg not installed, skip check
                    self.console.print(
                        "[yellow]⚠️  Database check skipped (psycopg not installed)[/yellow]"
                    )
                    return True
                except Exception as e:
                    if attempt < max_retries:
                        self.console.print(
                            f"[yellow]⚠ Attempt {attempt}/{max_retries} failed: {e}[/yellow]"
                        )
                        self.console.print(f"[dim]Retrying in {retry_delay}s...[/dim]")
                        time.sleep(retry_delay)
                    else:
                        self.console.print(
                            f"[red]❌ Database check failed after {max_retries} attempts: {e}[/red]"
                        )
                        return False

            return False

        # Run the verification with retries
        if not verify():
            self.console.print(
                "\n[red]❌ Database verification failed.[/red]\n"
                "[dim]Please ensure PostgreSQL is running and accessible.[/dim]\n"
            )

            if is_bundled_postgres_enabled():
                self.console.print(
                    "[dim]For bundled PostgreSQL, ensure it was deployed:[/dim]\n"
                    "  uv run api-forge-cli k8s db create\n"
                    "  uv run api-forge-cli k8s db init\n"
                )
            else:
                self.console.print(
                    "[dim]For external PostgreSQL, verify DATABASE_URL in .env[/dim]\n"
                )

            raise SystemExit(1)


def get_deployer() -> HelmDeployer:
    """Get the Helm deployer instance.

    Returns:
        HelmDeployer instance configured for current project
    """
    from src.cli.deployment.helm_deployer.deployer import HelmDeployer

    return HelmDeployer(console, CONTROLLER, DEFAULT_PATHS, DEFAULT_CONSTANTS)
