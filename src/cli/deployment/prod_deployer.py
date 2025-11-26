"""Production environment deployer."""

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .base import BaseDeployer
from .health_checks import HealthChecker
from .service_config import get_production_services
from .status_display import StatusDisplay


class ProdDeployer(BaseDeployer):
    """Deployer for production environment using Docker Compose."""

    COMPOSE_FILE = "docker-compose.prod.yml"
    DATA_SUBDIRS = [
        Path("postgres"),
        Path("postgres-backups"),
        Path("postgres-ssl"),
        Path("redis"),
        Path("redis-backups"),
        Path("app-logs"),
        Path("temporal-certs"),
    ]

    def __init__(self, console: Console, project_root: Path):
        """Initialize the production deployer.

        Args:
            console: Rich console for output
            project_root: Path to the project root directory
        """
        super().__init__(console, project_root)
        self.status_display = StatusDisplay(console)
        self.health_checker = HealthChecker()

        # Build services list dynamically based on config.yaml
        self.SERVICES = get_production_services()

    def deploy(self, **kwargs: Any) -> None:
        """Deploy the production environment.

        Args:
            **kwargs: Deployment options (skip_build, no_wait, force_recreate)
        """
        # Check for .env file first
        if not self.check_env_file():
            raise typer.Exit(1)

        self._ensure_required_directories()

        skip_build = kwargs.get("skip_build", False)
        no_wait = kwargs.get("no_wait", False)
        force_recreate = kwargs.get("force_recreate", False)

        # Build app image if needed (or force rebuild for secret rotation)
        if not skip_build or force_recreate:
            self._build_app_image(force=force_recreate)

        # For secret rotation, we need to stop and recreate containers
        if force_recreate:
            self.info(
                "Force recreate enabled - stopping containers to pick up new secrets..."
            )
            # Use teardown to stop containers properly
            self.teardown(volumes=False)

        # Start services (with force-recreate if specified)
        self._start_services(force_recreate=force_recreate)

        # Wait for health checks
        if not no_wait:
            self._monitor_health_checks()

        # Display final status
        self.console.print(
            "\n[bold green]🎉 Production deployment complete![/bold green]"
        )
        self.status_display.show_prod_status()

    def _ensure_required_directories(self) -> None:
        data_root = self.ensure_data_directories(self.DATA_SUBDIRS)
        self.info(f"Ensured data directories exist under {data_root}")

    def teardown(self, **kwargs: Any) -> None:
        """Stop the production environment.

        Args:
            **kwargs: Teardown options (volumes)
        """
        volumes = kwargs.get("volumes", False)

        # Find all production containers (api-forge-* but not *-dev)
        self.info("Finding production containers...")
        result = self.run_command(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=api-forge",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
        )

        if result and result.stdout:
            container_names = [
                name.strip()
                for name in result.stdout.strip().split("\n")
                if name.strip()
                and not name.endswith("-dev")
                and "keycloak" not in name  # Only exclude dev-environment keycloak
            ]

            if container_names:
                self.info(f"Found {len(container_names)} production containers to stop")
                with self.console.status("[bold red]Stopping containers..."):
                    for container in container_names:
                        self.run_command(
                            ["docker", "stop", container],
                            check=False,
                            capture_output=True,
                        )
                    for container in container_names:
                        self.run_command(
                            ["docker", "rm", container],
                            check=False,
                            capture_output=True,
                        )
                self.success(f"Stopped and removed {len(container_names)} containers")
            else:
                self.info("No production containers found to stop")
        else:
            self.info("No production containers found to stop")

        # Named volumes require explicit removal (docker compose down -v only removes anonymous volumes)
        if volumes:
            self.info("Removing named data volumes...")
            # Use the same consistent project name as _start_services
            project_name = "api-forge-prod"
            # Get list of volumes for this project
            result = self.run_command(
                [
                    "docker",
                    "volume",
                    "ls",
                    "-q",
                    "--filter",
                    f"label=com.docker.compose.project={project_name}",
                ],
                capture_output=True,
            )
            if result and result.stdout:
                volume_names = [v for v in result.stdout.strip().split("\n") if v]
                if volume_names:
                    for volume in volume_names:
                        self.run_command(
                            ["docker", "volume", "rm", volume],
                            check=False,
                            capture_output=True,
                        )
                    self.success(
                        f"Production services stopped and {len(volume_names)} volume objects removed"
                    )
                else:
                    self.success("Production services stopped (no volumes found)")
            else:
                self.success("Production services stopped and volumes removed")

            # Also remove the actual data directories (since volumes use bind mounts)
            self.info("Removing data directories...")
            data_dir = self.project_root / "data"
            if data_dir.exists():
                import shutil

                failed_dirs = []
                for subdir in self.DATA_SUBDIRS:
                    dir_path = data_dir / subdir
                    if dir_path.exists():
                        try:
                            shutil.rmtree(dir_path)
                        except PermissionError:
                            failed_dirs.append(dir_path)
                        except Exception as e:
                            self.console.print(
                                f"[yellow]Warning: Could not remove {dir_path}: {e}[/yellow]"
                            )

                # Retry failed directories with sudo
                if failed_dirs:
                    dir_list = ", ".join(
                        [str(d.relative_to(self.project_root)) for d in failed_dirs]
                    )
                    self.console.print(
                        f"[yellow]Elevated permissions required to remove: {dir_list}[/yellow]"
                    )
                    self.console.print(
                        "[yellow]Using sudo to remove Docker-created files...[/yellow]"
                    )
                    for dir_path in failed_dirs:
                        self.run_command(
                            ["sudo", "rm", "-rf", str(dir_path)], check=False
                        )
                self.success("Data directories removed")

        else:
            self.success("Production services stopped (volumes preserved)")

    def show_status(self) -> None:
        """Display the current status of the production deployment."""
        self.status_display.show_prod_status()

    def _build_app_image(self, force: bool = False) -> None:
        """Build the application Docker image using Docker layer caching.

        Args:
            force: If True, rebuild postgres image for secret rotation
        """
        with self.create_progress() as progress:
            # Build postgres first if force (for secret rotation with updated sync script)
            if force:
                task = progress.add_task(
                    "Rebuilding postgres image (for secret rotation)...", total=1
                )
                self.run_command(
                    [
                        "docker",
                        "compose",
                        "-f",
                        self.COMPOSE_FILE,
                        "build",
                        "postgres",
                    ]
                )
                progress.update(task, completed=1)
                self.success("Postgres image rebuilt")

            task = progress.add_task("Building application image...", total=1)
            self.run_command(
                [
                    "docker",
                    "compose",
                    "-f",
                    self.COMPOSE_FILE,
                    "build",
                    "app",
                ]
            )
            progress.update(task, completed=1)
        self.success("Application image built (using cached layers)")

    def _start_services(self, force_recreate: bool = False) -> None:
        """Start all production services.

        Args:
            force_recreate: If True, force recreate containers (for secret rotation)
        """
        with self.create_progress() as progress:
            task = progress.add_task("Starting production services...", total=1)
            # Use fixed project name to avoid conflicts with old networks
            cmd = [
                "docker",
                "compose",
                "-p",
                "api-forge-prod",
                "-f",
                self.COMPOSE_FILE,
                "up",
                "-d",
                "--remove-orphans",
            ]
            if force_recreate:
                cmd.append("--force-recreate")

            result = self.run_command(cmd, check=False)
            progress.update(task, completed=1)

            if result and result.returncode != 0:
                self.console.print(
                    "[yellow]⚠ Some services may have failed to start. Check the output above.[/yellow]"
                )
                self.console.print(
                    "[yellow]  Tip: Run 'uv run api-forge-cli deploy down prod' to clean up, then try again.[/yellow]"
                )
                raise typer.Exit(1)

        self.success("Production services started")

    def _monitor_health_checks(self) -> None:
        """Monitor health checks for all services."""
        self.console.print(
            "\n[bold cyan]🔍 Monitoring service health checks...[/bold cyan]"
        )
        self.console.print("[dim]This may take up to 90 seconds per service...[/dim]\n")

        # Create status table
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Service", style="cyan", width=20)
        table.add_column("Status", width=15)
        table.add_column("Details", style="dim")

        all_healthy = True

        # Check each service with retries
        for container_name, service_name in self.SERVICES:
            # Wait for container to become healthy (with timeout)
            def check_health(name: str = container_name) -> bool:
                is_healthy, _ = self.health_checker.check_container_health(name)
                return is_healthy

            is_healthy = self.health_checker.wait_for_condition(
                check_health, timeout=90, interval=3, service_name=service_name
            )

            # Get final status for display
            _, status = self.health_checker.check_container_health(container_name)

            if is_healthy:
                table.add_row(
                    service_name,
                    "[bold green]✓ Healthy[/bold green]",
                    status or "Running",
                )
            elif status == "starting":
                table.add_row(
                    service_name,
                    "[bold yellow]⚡ Starting[/bold yellow]",
                    "Still starting up...",
                )
                all_healthy = False
            elif status == "no-healthcheck":
                # For containers without health checks, just verify they're running
                result = self.run_command(
                    [
                        "docker",
                        "inspect",
                        "-f",
                        "{{.State.Running}}",
                        container_name,
                    ],
                    capture_output=True,
                )
                if result.stdout and result.stdout.strip().lower() == "true":
                    table.add_row(
                        service_name,
                        "[bold blue]● Running[/bold blue]",
                        "No health check configured",
                    )
                else:
                    table.add_row(
                        service_name,
                        "[bold red]✗ Not Running[/bold red]",
                        "Container stopped",
                    )
                    all_healthy = False
            else:
                table.add_row(
                    service_name,
                    "[bold red]✗ Unhealthy[/bold red]",
                    status or "Health check failed",
                )
                all_healthy = False

        # Display results
        self.console.print(
            Panel(table, title="Service Health Status", border_style="green")
        )

        if not all_healthy:
            self.warning(
                "Some services may need more time to become healthy. "
                "Check logs with: docker compose -f docker-compose.prod.yml logs [service]"
            )
