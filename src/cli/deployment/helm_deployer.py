"""Kubernetes environment deployer."""

import shutil
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from rich.console import Console

from src.app.runtime.config.config_loader import load_config

from .base import BaseDeployer
from .health_checks import HealthChecker
from .status_display import StatusDisplay


class HelmDeployer(BaseDeployer):
    """Deployer for Kubernetes environment using Helm."""

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
        self.helm_chart = project_root / "infra" / "helm" / "api-forge"
        self.helm_scripts = self.helm_chart / "scripts"
        self.helm_files = self.helm_chart / "files"

    def deploy(self, **kwargs: Any) -> None:
        """Deploy to Kubernetes cluster.

        Deployment workflow:
        1. Build Docker images
        2. Load images into Minikube
        3. Deploy secrets (from infra/secrets)
        4. Sync config.yaml settings to values.yaml
        5. Copy config files to infra/helm/api-forge/files/
        6. Create ConfigMaps from config files
        7. Deploy resources via Helm

        Args:
            **kwargs: Additional deployment options (namespace, no_wait, force_recreate)
        """
        # Check for .env file before deployment
        if not self.check_env_file():
            return

        namespace = kwargs.get("namespace", self.DEFAULT_NAMESPACE)
        force_recreate = kwargs.get("force_recreate", False)

        # Step 1: Build images (force rebuild for secret rotation)
        self._build_images(force=force_recreate)

        # Step 2: Load images to Minikube (handled in _build_images)

        # Step 3: Deploy secrets
        self._deploy_secrets(namespace)

        # Step 4: Sync config.yaml settings to values.yaml
        self._sync_config_to_values()

        # Step 5: Copy config files to helm staging area
        self._copy_config_files()

        # Step 5: ConfigMaps are now handled by Helm via files/ directory
        # (no separate step needed - Helm will create them during install)

        # Step 6: Deploy resources via Helm
        self._deploy_resources(namespace, force_recreate)

        # Display status
        self.console.print(
            "\n[bold green]🎉 Kubernetes deployment complete![/bold green]"
        )
        self.status_display.show_k8s_status(namespace)

    def teardown(self, **kwargs: Any) -> None:
        """Remove Kubernetes deployment.

        Args:
            **kwargs: Additional teardown options (volumes, namespace)
        """
        namespace = kwargs.get("namespace", self.DEFAULT_NAMESPACE)

        self.console.print(
            f"[bold red]Uninstalling Helm release from {namespace}...[/bold red]"
        )

        self.run_command(
            ["helm", "uninstall", "api-forge", "-n", namespace, "--wait"], check=False
        )

        with self.console.status(f"[bold red]Deleting namespace {namespace}..."):
            self.run_command(
                [
                    "kubectl",
                    "delete",
                    "namespace",
                    namespace,
                    "--wait=true",
                    "--timeout=120s",
                ],
                check=False,
            )

        self.success(f"Teardown complete for {namespace}")

    def show_status(self, namespace: str | None = None) -> None:
        """Display the current status of the Kubernetes deployment.

        Args:
            namespace: Kubernetes namespace to check (default: api-forge)
        """
        if namespace is None:
            namespace = self.DEFAULT_NAMESPACE
        self.status_display.show_k8s_status(namespace)

    def _build_images(self, force: bool = False) -> None:
        """Build Docker images for Kubernetes deployment.

        Args:
            force: If True, rebuild postgres image for secret rotation
        """
        self.console.print("[bold cyan]🔨 Building Docker images...[/bold cyan]")

        # If force, rebuild postgres image first
        if force:
            with self.create_progress() as progress:
                task = progress.add_task(
                    "Rebuilding postgres image (for secret rotation)...", total=1
                )
                self.run_command(
                    [
                        "docker",
                        "compose",
                        "-f",
                        "docker-compose.prod.yml",
                        "build",
                        "postgres",
                    ]
                )
                progress.update(task, completed=1)
            self.success("Postgres image rebuilt")

        script_path = self.helm_scripts / "build-images.sh"
        with self.create_progress() as progress:
            task = progress.add_task("Building images...", total=1)
            self.run_command(["bash", str(script_path)])
            progress.update(task, completed=1)

        self.success("Docker images built")

        # Load images into Minikube
        self._load_images_to_minikube()

    def _load_images_to_minikube(self) -> None:
        """Load Docker images into Minikube for local Kubernetes deployment."""
        self.console.print("[bold cyan]📦 Loading images into Minikube...[/bold cyan]")

        # All images use 'latest' tag for consistency
        images = [
            "api-forge-app:latest",
            "app_data_postgres_image:latest",
            "app_data_redis_image:latest",
            "my-temporal-server:latest",
        ]

        with self.create_progress() as progress:
            task = progress.add_task("Loading images...", total=len(images))
            for image in images:
                self.run_command(["minikube", "image", "load", image], check=False)
                progress.update(task, advance=1)

        self.success("Images loaded into Minikube")

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
            self.console.print(
                "[bold yellow]🔑 Generating secrets (first time setup)...[/bold yellow]"
            )

            generate_script = secrets_dir / "generate_secrets.sh"
            if not generate_script.exists():
                self.error(f"Secret generation script not found: {generate_script}")
                raise RuntimeError("Cannot generate secrets - script missing")

            # Generate secrets and PKI certificates
            # Note: generate_secrets.sh without flags generates secret keys
            # The --generate-pki flag is ONLY for certificates, so we combine both
            with self.create_progress() as progress:
                task = progress.add_task(
                    "Generating secrets and certificates...", total=1
                )
                # First generate secrets (passwords, signing keys, etc.)
                self.run_command(["bash", str(generate_script)])
                # Then generate PKI certificates
                self.run_command(["bash", str(generate_script), "--generate-pki"])
                progress.update(task, completed=1)

            self.success("Secrets and certificates generated successfully")
        else:
            self.console.print("[dim]✓ Secrets already exist[/dim]")

    def _deploy_secrets(self, namespace: str) -> None:
        """Deploy Kubernetes secrets using helm/scripts/apply-secrets.sh.

        This assumes secrets have already been generated in infra/secrets/.
        If not found, it will attempt to generate them.

        Args:
            namespace: Target namespace
        """
        # Generate secrets if needed (first-time setup)
        self._generate_secrets_if_needed()

        self.console.print("[bold cyan]🔐 Deploying Kubernetes secrets...[/bold cyan]")

        # Use the apply-secrets.sh script from helm/scripts
        script_path = self.helm_scripts / "apply-secrets.sh"

        if not script_path.exists():
            self.error(f"Secret deployment script not found: {script_path}")
            raise RuntimeError("Cannot deploy secrets - script missing")

        with self.create_progress() as progress:
            task = progress.add_task("Deploying secrets...", total=1)
            self.run_command(["bash", str(script_path), namespace])
            progress.update(task, completed=1)

        self.success(f"Secrets deployed to namespace {namespace}")

    def _sync_config_to_values(self) -> None:
        """Synchronize settings from config.yaml to values.yaml.

        This ensures that service enable/disable flags are consistent between
        the application config and Helm deployment values.

        Synced settings:
        - redis.enabled
        - temporal.enabled
        """
        self.console.print(
            "[bold cyan]🔄 Synchronizing config.yaml → values.yaml...[/bold cyan]"
        )

        config_path = self.project_root / "config.yaml"
        values_path = self.helm_chart / "values.yaml"

        if not config_path.exists():
            self.console.print(
                "[yellow]⚠️  config.yaml not found, skipping sync[/yellow]"
            )
            return

        try:
            # Load config.yaml using the config loader (returns dict with processed=False)
            config_raw = load_config(config_path, processed=False)
            # Access the actual config section
            config_data = config_raw if isinstance(config_raw, dict) else {}

            # Load values.yaml
            with open(values_path) as f:
                values_data = yaml.safe_load(f)

            # Track changes
            changes = []

            # Sync redis.enabled
            if "config" in config_data and "redis" in config_data["config"]:
                redis_enabled = config_data["config"]["redis"].get("enabled", True)
                if "redis" in values_data:
                    old_value = values_data["redis"].get("enabled", True)
                    if old_value != redis_enabled:
                        values_data["redis"]["enabled"] = redis_enabled
                        changes.append(f"redis.enabled: {old_value} → {redis_enabled}")

            # Sync temporal.enabled
            if "config" in config_data and "temporal" in config_data["config"]:
                temporal_enabled = config_data["config"]["temporal"].get(
                    "enabled", True
                )
                if "temporal" in values_data:
                    old_value = values_data["temporal"].get("enabled", True)
                    if old_value != temporal_enabled:
                        values_data["temporal"]["enabled"] = temporal_enabled
                        changes.append(
                            f"temporal.enabled: {old_value} → {temporal_enabled}"
                        )

            # Write back values.yaml if changes were made
            if changes:
                with open(values_path, "w") as f:
                    yaml.safe_dump(
                        values_data,
                        f,
                        default_flow_style=False,
                        sort_keys=False,
                        allow_unicode=True,
                    )

                self.console.print("[green]✓ Synced changes:[/green]")
                for change in changes:
                    self.console.print(f"  • {change}")
            else:
                self.console.print(
                    "[dim]  ✓ No changes needed (values already in sync)[/dim]"
                )

        except Exception as e:
            self.console.print(f"[yellow]⚠️  Failed to sync config: {e}[/yellow]")
            self.console.print(
                "[dim]  Continuing with deployment using existing values.yaml[/dim]"
            )

    def _copy_config_files(self) -> None:
        """Copy configuration files from project root to infra/helm/api-forge/files/.

        This copies:
        - .env → files/.env
        - config.yaml → files/config.yaml
        - PostgreSQL configs (postgresql.conf, pg_hba.conf, init scripts)
        - Temporal scripts
        - Universal entrypoint script
        """
        self.console.print(
            "[bold cyan]📋 Copying config files to Helm staging area...[/bold cyan]"
        )

        # Ensure files directory exists
        self.helm_files.mkdir(parents=True, exist_ok=True)

        # Track files to copy: (source_path, dest_name, description)
        files_to_copy = []

        # 1. .env file
        env_file = self.project_root / ".env"
        if env_file.exists():
            files_to_copy.append((env_file, ".env", "Environment variables"))

        # 2. config.yaml
        config_file = self.project_root / "config.yaml"
        if config_file.exists():
            files_to_copy.append((config_file, "config.yaml", "Application config"))

        # 3. PostgreSQL configs
        pg_dir = self.project_root / "infra" / "docker" / "prod" / "postgres"
        pg_files = [
            (pg_dir / "postgresql.conf", "postgresql.conf", "PostgreSQL config"),
            (pg_dir / "pg_hba.conf", "pg_hba.conf", "PostgreSQL HBA config"),
            (
                pg_dir / "verify-init.sh",
                "verify-init.sh",
                "PostgreSQL verifier script",
            ),
        ]
        files_to_copy.extend(pg_files)

        # 4. PostgreSQL init scripts
        pg_init_dir = pg_dir / "init-scripts"
        if (pg_init_dir / "01-init-app.sh").exists():
            files_to_copy.append(
                (
                    pg_init_dir / "01-init-app.sh",
                    "01-init-app.sh",
                    "PostgreSQL init script",
                )
            )

        # 5. Universal entrypoint
        universal_entrypoint = (
            self.project_root
            / "infra"
            / "docker"
            / "prod"
            / "scripts"
            / "universal-entrypoint.sh"
        )
        if universal_entrypoint.exists():
            files_to_copy.append(
                (
                    universal_entrypoint,
                    "universal-entrypoint.sh",
                    "Universal entrypoint",
                )
            )

        # 6. Temporal scripts
        temporal_dir = (
            self.project_root / "infra" / "docker" / "prod" / "temporal" / "scripts"
        )
        temporal_files_dir = self.helm_files / "temporal"
        temporal_files_dir.mkdir(exist_ok=True)

        temporal_scripts = [
            (
                temporal_dir / "schema-setup.sh",
                "temporal/schema-setup.sh",
                "Temporal schema setup",
            ),
            (
                temporal_dir / "entrypoint.sh",
                "temporal/entrypoint.sh",
                "Temporal entrypoint",
            ),
            (
                temporal_dir / "namespace-init.sh",
                "temporal/namespace-init.sh",
                "Temporal namespace init",
            ),
        ]
        files_to_copy.extend(temporal_scripts)

        # Copy all files
        with self.create_progress() as progress:
            task = progress.add_task("Copying files...", total=len(files_to_copy))

            for source, dest_name, description in files_to_copy:
                if source.exists():
                    dest_path = self.helm_files / dest_name
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest_path)
                    self.console.print(f"  [dim]✓ {description}[/dim]")
                else:
                    self.console.print(
                        f"  [yellow]⚠ Skipped {description} (not found)[/yellow]"
                    )
                progress.update(task, advance=1)

        self.success(
            f"Config files copied to {self.helm_files.relative_to(self.project_root)}"
        )

    def _cleanup_stuck_release(self, release_name: str, namespace: str) -> bool:
        """Clean up Helm release stuck in problematic states.

        Args:
            release_name: Name of the Helm release
            namespace: Target namespace

        Returns:
            True if cleanup was performed, False if no cleanup needed
        """
        # Check release status
        result = self.run_command(
            [
                "helm",
                "list",
                "-n",
                namespace,
                "--uninstalling",
                "--pending",
                "--failed",
                "-o",
                "json",
            ],
            capture_output=True,
        )

        if result.returncode != 0:
            return False

        # Parse JSON output to check for our release
        import json

        try:
            releases = json.loads(result.stdout)
            stuck_release = None

            for release in releases:
                if release.get("name") == release_name:
                    stuck_release = release
                    break

            if not stuck_release:
                return False

            status = stuck_release.get("status", "")
            self.warning(
                f"Found release '{release_name}' in '{status}' state. Cleaning up..."
            )

            # Try to uninstall the stuck release
            uninstall_result = self.run_command(
                ["helm", "uninstall", release_name, "-n", namespace, "--wait"],
                capture_output=True,
            )

            if uninstall_result.returncode == 0:
                self.success(f"Successfully cleaned up stuck release '{release_name}'")
                return True
            else:
                # If uninstall fails, try force delete
                self.warning("Normal uninstall failed. Attempting force cleanup...")

                # Delete all resources with the release label
                self.run_command(
                    [
                        "kubectl",
                        "delete",
                        "all,configmap,secret,pvc",
                        "-n",
                        namespace,
                        "-l",
                        f"app.kubernetes.io/instance={release_name}",
                        "--force",
                        "--grace-period=0",
                    ],
                    capture_output=True,
                )

                # Remove Helm release metadata
                self.run_command(
                    [
                        "kubectl",
                        "delete",
                        "secret",
                        "-n",
                        namespace,
                        "-l",
                        f"name={release_name},owner=helm",
                    ],
                    capture_output=True,
                )

                self.success(f"Force cleaned up release '{release_name}'")
                return True

        except (json.JSONDecodeError, KeyError) as e:
            self.warning(f"Could not parse release status: {e}")
            return False

    def _deploy_resources(self, namespace: str, force_recreate: bool = False) -> None:
        """Deploy Kubernetes resources via Helm.

        Args:
            namespace: Target namespace
            force_recreate: Whether to force recreate pods
        """
        # Check for and clean up any stuck releases
        self._cleanup_stuck_release("api-forge", namespace)

        self.console.print("[bold cyan]🚀 Deploying resources via Helm...[/bold cyan]")

        cmd = [
            "helm",
            "upgrade",
            "--install",
            "api-forge",
            str(self.helm_chart),
            "--namespace",
            namespace,
            "--create-namespace",
            "--rollback-on-failure",
            "--wait",
            "--wait-for-jobs",
            "--timeout",
            "10m",
        ]

        self.console.print("[bold cyan]🚀 Deploying resources via Helm...[/bold cyan]")
        self.console.print(f"[dim]Running command: {' '.join(cmd)}[/dim]")

        # Run without progress bar to show Helm output
        self.run_command(cmd, check=True)

        if force_recreate:
            self.info("Force recreating pods...")
            self.run_command(
                ["kubectl", "rollout", "restart", "deployment", "-n", namespace]
            )

        self.success(f"Resources deployed to namespace {namespace}")

    def _wait_for_pods(self, namespace: str) -> None:
        """Wait for all pods to be ready.

        Args:
            namespace: Target namespace
        """
        self.console.print(
            "\n[bold cyan]⏳ Waiting for pods to be ready...[/bold cyan]"
        )
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
                    "-l",
                    "app.kubernetes.io/component in (application,database,cache,workflow-engine,temporal-worker,workflow-ui)",
                    "-n",
                    namespace,
                    "--timeout=300s",
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
