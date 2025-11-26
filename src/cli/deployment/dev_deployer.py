"""Development environment deployer."""

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.progress import Progress

from src.dev.dev_utils import (
    check_container_running,
    check_postgres_status,
    check_redis_status,
    check_temporal_status,
    run_keycloak_setup,
    wait_for_keycloak,
)
from src.utils.package_utils import get_package_module_path, get_package_root

from .base import BaseDeployer
from .health_checks import HealthChecker
from .status_display import StatusDisplay


class DevDeployer(BaseDeployer):
    """Deployer for development environment using Docker Compose."""

    COMPOSE_FILE = "docker-compose.dev.yml"
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
        """Initialize the development deployer.

        Args:
            console: Rich console for output
            project_root: Path to the project root directory
        """
        super().__init__(console, project_root)
        self.status_display = StatusDisplay(console)
        self.health_checker = HealthChecker()

    def deploy(self, **kwargs: Any) -> None:
        """Deploy the development environment.

        Args:
            **kwargs: Deployment options (force, no_wait, start_server)
        """
        # Check for .env file first
        if not self.check_env_file():
            raise typer.Exit(1)

        self._ensure_required_directories()

        force = kwargs.get("force", False)
        no_wait = kwargs.get("no_wait", False)
        start_server = kwargs.get("start_server", True)
        # Check if services are already running
        running_services = self._get_running_services()
        all_services_running = (
            len(running_services) == 4
        )  # Keycloak, Postgres, Redis, Temporal

        if all_services_running and not force:
            self.success("All services are already running and healthy!")
            self.console.print(
                "[bold yellow]💡 Tip: Use --force to restart all services[/bold yellow]"
            )
            self.console.print(
                "\n[bold green]🎉 Development environment is ready![/bold green]"
            )
            self.status_display.show_dev_status()
            # Continue to start dev server even if services are already running
            if start_server:
                self._start_dev_server()
            return

        if running_services and force:
            self.warning(f"Found running services: {', '.join(running_services)}")
            self.console.print(
                "[yellow]🔄 Restarting all services with --force flag...[/yellow]"
            )
            self._stop_services()
        elif running_services:
            self.warning(
                f"Some services are already running: {', '.join(running_services)}"
            )
            self.console.print(
                "[bold yellow]💡 To avoid conflicts, please use --force to restart all services[/bold yellow]"
            )
            raise typer.Exit(0)

        # Start services
        self._start_services(no_wait)

        # Start the development server
        if start_server:
            self._start_dev_server()

    def _ensure_required_directories(self) -> None:
        data_root = self.ensure_data_directories(self.DATA_SUBDIRS)
        self.info(f"Ensured data directories exist under {data_root}")

    def teardown(self, **kwargs: Any) -> None:
        """Stop the development environment.

        Args:
            **kwargs: Teardown options (volumes)
        """
        volumes = kwargs.get("volumes", False)
        cmd = ["docker", "compose", "-f", self.COMPOSE_FILE, "down", "--remove-orphans"]
        if volumes:
            cmd.append("-v")

        with self.console.status("[bold red]Stopping containers..."):
            self.run_command(cmd)

        self.success("Development services stopped")

    def show_status(self) -> None:
        """Display the current status of the development deployment."""
        self.status_display.show_dev_status()

    def _get_running_services(self) -> list[str]:
        """Get list of currently running development services.

        Returns:
            List of service names that are running
        """
        services = []
        if check_container_running("api-forge-keycloak-dev"):
            services.append("Keycloak")
        if check_container_running("api-forge-postgres-dev"):
            services.append("PostgreSQL")
        if check_container_running("api-forge-redis-dev"):
            services.append("Redis")
        if check_container_running("api-forge-temporal-dev"):
            services.append("Temporal")
        return services

    def _stop_services(self) -> None:
        """Stop all development services."""
        with self.create_progress() as progress:
            task = progress.add_task("Stopping existing containers...", total=1)
            self.run_command(
                [
                    "docker",
                    "compose",
                    "-f",
                    self.COMPOSE_FILE,
                    "down",
                    "--remove-orphans",
                ]
            )
            progress.update(task, completed=1)

    def _start_services(self, no_wait: bool) -> None:
        """Start all development services and wait for them to be ready.

        Args:
            no_wait: Don't wait for services to be ready
        """
        with self.create_progress() as progress:
            # Start containers
            task1 = progress.add_task("Starting Docker containers...", total=1)
            self.run_command(
                [
                    "docker",
                    "compose",
                    "-f",
                    self.COMPOSE_FILE,
                    "up",
                    "-d",
                    "--remove-orphans",
                ]
            )
            progress.update(task1, completed=1)

            if not no_wait:
                self._wait_for_services(progress)

    def _wait_for_services(self, progress: Progress) -> None:
        """Wait for all services to be ready.

        Args:
            progress: Progress instance to update
        """
        # Wait for PostgreSQL
        task2 = progress.add_task("Waiting for PostgreSQL to be ready...", total=1)
        if self.health_checker.wait_for_condition(
            check_postgres_status, timeout=30, service_name="PostgreSQL"
        ):
            progress.update(task2, completed=1)
            self.success("PostgreSQL is ready")
        else:
            self.warning("PostgreSQL may not be fully ready yet")

        # Wait for Keycloak
        task3 = progress.add_task("Waiting for Keycloak to be ready...", total=1)
        if wait_for_keycloak():
            progress.update(task3, completed=1)
            self.success("Keycloak is ready")

            # Configure Keycloak
            task4 = progress.add_task("Configuring Keycloak...", total=1)
            if run_keycloak_setup():
                progress.update(task4, completed=1)
                self.success("Keycloak configured")
            else:
                self.warning("Keycloak setup failed - you may need to run it manually")
        else:
            self.error("Keycloak failed to start within timeout")
            raise typer.Exit(1)

        # Wait for Redis
        task5 = progress.add_task("Waiting for Redis to be ready...", total=1)
        if self.health_checker.wait_for_condition(
            check_redis_status, timeout=20, service_name="Redis"
        ):
            progress.update(task5, completed=1)
            self.success("Redis is ready")
        else:
            self.warning("Redis may not be fully ready yet")

        # Wait for Temporal
        task6 = progress.add_task("Waiting for Temporal to be ready...", total=1)
        if self.health_checker.wait_for_condition(
            check_temporal_status, timeout=60, interval=5, service_name="Temporal"
        ):
            progress.update(task6, completed=1)
            self.success("Temporal is ready")
        else:
            self.warning("Temporal may not be fully ready yet")

    def _start_dev_server(self) -> None:
        """Start the FastAPI development server with hot reload."""
        self.console.print(
            "\n[bold green]🎉 Development environment is ready![/bold green]"
        )
        self.status_display.show_dev_status()

        self.console.print(
            "\n[bold cyan]🚀 Starting FastAPI Development Server...[/bold cyan]"
        )
        self.console.print(
            "[dim]The server will run with hot reload enabled. Press Ctrl+C to stop.[/dim]\n"
        )

        try:
            # Dynamically detect package name
            package_name = get_package_module_path()
            package_root = get_package_root()

            self.run_command(
                [
                    "uv",
                    "run",
                    "uvicorn",
                    f"{package_name}.app.api.http.app:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8000",
                    "--reload",
                    "--reload-dir",
                    str(package_root),
                    "--log-level",
                    "info",
                ]
            )
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Server stopped by user[/yellow]")
        except Exception as exc:
            self.error("Failed to start development server")
            raise typer.Exit(1) from exc
