"""Status display utilities for deployment environments."""

import os
import subprocess

import requests  # type: ignore
from dotenv.main import load_dotenv
from rich.console import Console
from rich.panel import Panel

from src.dev.dev_utils import (
    check_container_running,
    check_docker_running,
    check_postgres_status,
    check_redis_status,
    check_temporal_status,
)

from .health_checks import HealthChecker
from .service_config import get_production_services


class StatusDisplay:
    """Utility class for displaying deployment status."""

    def __init__(self, console: Console):
        """Initialize the status display.

        Args:
            console: Rich console for output
        """
        self.console = console
        self.health_checker = HealthChecker()

    def show_dev_status(self) -> None:
        """Display development environment status."""
        self.console.print(
            Panel.fit(
                "[bold cyan]Development Services Status[/bold cyan]",
                border_style="cyan",
            )
        )

        load_dotenv()

        app_db = os.getenv("APP_DB", "appdb")
        app_user = os.getenv("APP_DB_USER", "appuser")
        app_password = os.getenv("APP_DB_USER_PW", "devpass")

        # Docker
        self._show_docker_status()

        # Keycloak
        self._show_keycloak_status()

        # PostgreSQL
        self._show_postgres_dev_status(app_db, app_user, app_password)

        # Redis
        self._show_redis_dev_status()

        # Temporal
        self._show_temporal_dev_status()

    def show_prod_status(self) -> None:
        """Display production environment status."""
        self.console.print(
            Panel.fit(
                "[bold green]Production Services Status[/bold green]",
                border_style="green",
            )
        )

        # Get list of active services from common config
        services = get_production_services()

        for container_name, service_name in services:
            is_healthy, status = self.health_checker.check_container_health(
                container_name
            )
            self._print_service_status(service_name, is_healthy, status)

        self._show_prod_access_urls()

    def show_k8s_status(self, namespace: str = "api-forge-prod") -> None:
        """Display Kubernetes deployment status.

        Args:
            namespace: Kubernetes namespace to check
        """
        self.console.print(
            Panel.fit(
                "[bold magenta]Kubernetes Deployment Status[/bold magenta]",
                border_style="magenta",
            )
        )

        # Get pod status
        result = subprocess.run(
            ["kubectl", "get", "pods", "-n", namespace, "-o", "wide"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            self.console.print("\n[bold cyan]Pods:[/bold cyan]")
            self.console.print(result.stdout)

        # Get service status
        result = subprocess.run(
            ["kubectl", "get", "svc", "-n", namespace],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            self.console.print("\n[bold cyan]Services:[/bold cyan]")
            self.console.print(result.stdout)

        self._show_k8s_access_instructions(namespace)

    def _show_docker_status(self) -> None:
        """Display Docker daemon status."""
        docker_running = check_docker_running()
        status_text = (
            "[green]✅ Running[/green]"
            if docker_running
            else "[red]❌ Not running[/red]"
        )
        self.console.print(f"Docker: {status_text}")

    def _show_keycloak_status(self) -> None:
        """Display Keycloak status."""
        keycloak_running = check_container_running("api-forge-keycloak-dev")
        status_text = (
            "[green]✅ Running[/green]"
            if keycloak_running
            else "[red]❌ Not running[/red]"
        )
        self.console.print(f"Keycloak: {status_text}")

        if keycloak_running:
            try:
                response = requests.get(
                    "http://localhost:8080/realms/master", timeout=5
                )
                if response.status_code == 200:
                    self.console.print("  └─ Health: [green]✅ Ready[/green]")
                    self.console.print("  └─ Server: http://localhost:8080")
                    self.console.print(
                        "  └─ Admin UI: http://localhost:8080/admin/master/console/"
                    )
            except requests.exceptions.RequestException:
                self.console.print("  └─ Health: [yellow]⚠️  Cannot connect[/yellow]")

    def _show_postgres_dev_status(
        self, app_db: str, app_user: str, app_password: str
    ) -> None:
        """Display PostgreSQL development status."""
        postgres_running = check_container_running("api-forge-postgres-dev")
        status_text = (
            "[green]✅ Running[/green]"
            if postgres_running
            else "[red]❌ Not running[/red]"
        )
        self.console.print(f"PostgreSQL: {status_text}")

        if postgres_running and check_postgres_status():
            self.console.print("  └─ Health: [green]✅ Ready[/green]")
            self.console.print(
                "  └─ Server: postgresql://appuser:devpass@localhost:5433/appdb"
            )
            self.console.print(f"  └─ Database: {app_db}")
            self.console.print(f"  └─ Username: {app_user}")
            self.console.print(f"  └─ Password: {app_password}")
            self.console.print(
                f"  └─ Connection (localhost): "
                f"[cyan]postgresql://{app_user}:{app_password}@localhost:5433/{app_db}[/cyan]"
            )
            self.console.print(
                f"  └─ Connection (container): "
                f"[cyan]postgresql://{app_user}:{app_password}@app_dev_postgres_db:5432/{app_db}[/cyan]"
            )

    def _show_redis_dev_status(self) -> None:
        """Display Redis development status."""
        redis_running = check_container_running("api-forge-redis-dev")
        status_text = (
            "[green]✅ Running[/green]"
            if redis_running
            else "[red]❌ Not running[/red]"
        )
        self.console.print(f"Redis: {status_text}")

        if redis_running and check_redis_status():
            self.console.print("  └─ Health: [green]✅ Ready[/green]")
            self.console.print("  └─ Server: redis://localhost:6380/0")

    def _show_temporal_dev_status(self) -> None:
        """Display Temporal development status."""
        temporal_server_running = check_container_running("api-forge-temporal-dev")
        temporal_web_running = check_container_running("api-forge-temporal-ui-dev")

        status_text = (
            "[green]✅ Running[/green]"
            if temporal_server_running
            else "[red]❌ Not running[/red]"
        )
        self.console.print(f"Temporal: {status_text}")

        if temporal_server_running and check_temporal_status():
            self.console.print("  └─ Health: [green]✅ Ready[/green]")
            self.console.print("  └─ Server: localhost:7234")
            self.console.print("  └─ Protocol: gRPC")

            if temporal_web_running:
                self.console.print(
                    "  └─ Web UI: [green]✅ http://localhost:8082[/green]"
                )

    def _print_service_status(
        self, service_name: str, is_healthy: bool, status: str
    ) -> None:
        """Print a service status line.

        Args:
            service_name: Name of the service
            is_healthy: Whether the service is healthy
            status: Status message
        """
        if not is_healthy:
            self.console.print(f"{service_name}: [red]❌ Not running[/red]")
        elif status == "healthy":
            self.console.print(f"{service_name}: [green]✅ Healthy[/green]")
        elif status == "running" or status == "no-healthcheck":
            self.console.print(f"{service_name}: [green]✅ Running[/green]")
        else:
            self.console.print(
                f"{service_name}: [yellow]⚠️  {status.capitalize()}[/yellow]"
            )

    def _show_prod_access_urls(self) -> None:
        """Display production environment access URLs."""
        self.console.print("\n[bold cyan]Access URLs:[/bold cyan]")
        self.console.print("  └─ API: http://localhost:8000")
        self.console.print("  └─ Health: http://localhost:8000/health")
        self.console.print("  └─ API Docs: http://localhost:8000/docs")
        self.console.print("  └─ Temporal Web: http://localhost:8081")

    def _show_k8s_access_instructions(self, namespace: str) -> None:
        """Display Kubernetes access instructions.

        Args:
            namespace: Kubernetes namespace
        """
        self.console.print("\n[bold cyan]Access Instructions:[/bold cyan]")
        self.console.print(
            f"  └─ Port-forward to app: kubectl port-forward -n {namespace} svc/app 8000:8000"
        )
        self.console.print(
            f"  └─ Port-forward to Temporal Web: kubectl port-forward -n {namespace} svc/temporal-web 8080:8080"
        )
        self.console.print(
            f"  └─ View logs: kubectl logs -n {namespace} -l app.kubernetes.io/name=app -f"
        )
