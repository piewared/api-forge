"""Kubernetes environment deployer."""

from pathlib import Path

from rich.console import Console

from .base import BaseDeployer
from .health_checks import HealthChecker
from .status_display import StatusDisplay


class K8sDeployer(BaseDeployer):
    """Deployer for Kubernetes environment."""

    DEFAULT_NAMESPACE = "api-forge-prod"

    def __init__(self, console: Console, project_root: Path):
        """Initialize the Kubernetes deployer.

        Args:
            console: Rich console for output
            project_root: Path to the project root directory
        """
        super().__init__(console, project_root)
        self.status_display = StatusDisplay(console)
        self.health_checker = HealthChecker()
        self.k8s_scripts = project_root / "k8s" / "scripts"

    def deploy(self, **kwargs) -> None:
        """Deploy to Kubernetes cluster.

        Args:
            **kwargs: Additional deployment options
        """
        # Check for .env file before deployment
        if not self.check_env_file():
            return

        namespace = kwargs.get("namespace", self.DEFAULT_NAMESPACE)

        # Build images
        self._build_images()

        # Create secrets
        self._create_secrets(namespace)

        # Deploy resources
        self._deploy_resources(namespace)

        # Wait for pods to be ready
        self._wait_for_pods(namespace)

        # Display status
        self.console.print("\n[bold green]🎉 Kubernetes deployment complete![/bold green]")
        self.status_display.show_k8s_status(namespace)

    def teardown(self, **kwargs) -> None:
        """Remove Kubernetes deployment.

        Args:
            **kwargs: Additional teardown options
        """
        namespace = kwargs.get("namespace", self.DEFAULT_NAMESPACE)

        with self.console.status(f"[bold red]Deleting namespace {namespace}..."):
            self.run_command(["kubectl", "delete", "namespace", namespace, "--wait=true"])

        self.success(f"Namespace {namespace} deleted")

    def show_status(self, namespace: str | None = None) -> None:
        """Display the current status of the Kubernetes deployment.

        Args:
            namespace: Kubernetes namespace to check (default: api-forge)
        """
        if namespace is None:
            namespace = self.DEFAULT_NAMESPACE
        self.status_display.show_k8s_status(namespace)

    def _build_images(self) -> None:
        """Build Docker images for Kubernetes deployment."""
        self.console.print("[bold cyan]🔨 Building Docker images...[/bold cyan]")

        script_path = self.k8s_scripts / "build-images.sh"
        with self.create_progress() as progress:
            task = progress.add_task("Building images...", total=1)
            self.run_command(["bash", str(script_path)])
            progress.update(task, completed=1)

        self.success("Docker images built")

    def _generate_secrets_if_needed(self) -> None:
        """Generate secrets if they don't exist."""
        secrets_dir = self.project_root / "infra" / "secrets"
        keys_dir = secrets_dir / "keys"

        # Check if secrets have been generated
        required_files = [
            keys_dir / "postgres_password.txt",
            keys_dir / "session_signing_secret.txt",
            keys_dir / "csrf_signing_secret.txt",
        ]

        secrets_exist = all(f.exists() for f in required_files)

        if not secrets_exist:
            self.console.print("[bold yellow]🔑 Generating secrets (first time setup)...[/bold yellow]")

            generate_script = secrets_dir / "generate_secrets.sh"
            if not generate_script.exists():
                self.error(f"Secret generation script not found: {generate_script}")
                raise RuntimeError("Cannot generate secrets - script missing")

            # Generate secrets and PKI certificates
            # Note: generate_secrets.sh without flags generates secret keys
            # The --generate-pki flag is ONLY for certificates, so we combine both
            with self.create_progress() as progress:
                task = progress.add_task("Generating secrets and certificates...", total=1)
                # First generate secrets (passwords, signing keys, etc.)
                self.run_command(["bash", str(generate_script)])
                # Then generate PKI certificates
                self.run_command(["bash", str(generate_script), "--generate-pki"])
                progress.update(task, completed=1)

            self.success("Secrets and certificates generated successfully")
        else:
            self.console.print("[dim]✓ Secrets already exist[/dim]")

    def _create_secrets(self, namespace: str) -> None:
        """Create Kubernetes secrets.

        Args:
            namespace: Target namespace
        """
        # Generate secrets if needed
        self._generate_secrets_if_needed()

        self.console.print("[bold cyan]🔐 Applying Kubernetes secrets...[/bold cyan]")

        script_path = self.k8s_scripts / "apply-secrets.sh"
        with self.create_progress() as progress:
            task = progress.add_task("Applying secrets...", total=1)
            self.run_command(["bash", str(script_path), namespace])
            progress.update(task, completed=1)

        self.success(f"Secrets applied in namespace {namespace}")

    def _deploy_resources(self, namespace: str) -> None:
        """Deploy Kubernetes resources.

        Args:
            namespace: Target namespace
        """
        self.console.print("[bold cyan]🚀 Deploying resources...[/bold cyan]")

        script_path = self.k8s_scripts / "deploy-resources.sh"
        with self.create_progress() as progress:
            task = progress.add_task("Deploying resources...", total=1)
            self.run_command(["bash", str(script_path), namespace])
            progress.update(task, completed=1)

        self.success(f"Resources deployed to namespace {namespace}")

    def _wait_for_pods(self, namespace: str) -> None:
        """Wait for all pods to be ready.

        Args:
            namespace: Target namespace
        """
        self.console.print("\n[bold cyan]⏳ Waiting for pods to be ready...[/bold cyan]")
        self.console.print("[dim]This may take 2-3 minutes...[/dim]\n")

        # Wait for deployment pods only (exclude jobs which complete and won't be "ready")
        # Using label selector to target only deployment-managed pods
        try:
            self.run_command(
                [
                    "kubectl",
                    "wait",
                    "--for=condition=ready",
                    "pod",
                    "-l", "app.kubernetes.io/component in (api,database,cache,workflow-engine,worker,web-ui)",
                    "-n",
                    namespace,
                    "--timeout=180s",
                ],
                capture_output=False,
            )
            self.success("All pods are ready")
        except Exception as e:
            self.warning(f"Some pods may not be fully ready yet: {e}")
            self.console.print(
                "\n[yellow]💡 Tip: Check pod status with: "
                f"kubectl get pods -n {namespace}[/yellow]"
            )
