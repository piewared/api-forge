"""Development environment CLI commands.

This module provides commands for managing the Docker Compose
development environment including Keycloak, PostgreSQL, Redis, and Temporal.

Commands:
    up      - Start the development environment
    down    - Stop the development environment
    status  - Show status of development services
    logs    - View logs from a service
    restart - Restart a specific service
"""

import subprocess
from pathlib import Path

import typer

from src.cli.deployment import DevDeployer
from src.cli.deployment.helm_deployer.image_builder import DeploymentError
from src.cli.shared.compose import ComposeRunner
from src.cli.shared.console import console
from src.utils.paths import get_project_root

# Create the dev command group
app = typer.Typer(
    name="dev",
    help="🔧 Development environment commands (Docker Compose)",
    no_args_is_help=True,
)


def _get_deployer() -> DevDeployer:
    """Create a DevDeployer instance with current project context."""
    return DevDeployer(console, Path(get_project_root()))


def _get_compose_runner() -> ComposeRunner:
    """Create a ComposeRunner for the dev compose file."""
    project_root = Path(get_project_root())
    return ComposeRunner(
        project_root,
        compose_file=project_root / "docker-compose.dev.yml",
    )


# =============================================================================
# Commands
# =============================================================================


@app.command()
def up(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force restart even if services are already running",
    ),
    no_wait: bool = typer.Option(
        False,
        "--no-wait",
        help="Don't wait for services to be healthy",
    ),
    start_server: bool = typer.Option(
        True,
        "--start-server/--no-start-server",
        help="Start FastAPI dev server after services are ready",
    ),
) -> None:
    """🚀 Start the development environment.

    Starts all development services (Keycloak, PostgreSQL, Redis, Temporal)
    using Docker Compose, then optionally starts the FastAPI development server.

    Examples:
        # Start everything including dev server
        api-forge-cli dev up

        # Start services only, no dev server
        api-forge-cli dev up --no-start-server

        # Force restart all services
        api-forge-cli dev up --force
    """
    console.print_header("Starting Development Environment")

    try:
        deployer = _get_deployer()
        deployer.deploy(force=force, no_wait=no_wait, start_server=start_server)
    except DeploymentError as e:
        console.handle_error(f"Deployment failed: {e.message}", e.details)


@app.command()
def down(
    volumes: bool = typer.Option(
        False,
        "--volumes",
        "-v",
        help="Also remove data volumes (DESTROYS ALL DATA)",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
) -> None:
    """⏹️  Stop the development environment.

    Stops all Docker Compose services. Use --volumes to also remove
    persistent data (databases, caches).

    Examples:
        # Stop services (preserves data)
        api-forge-cli dev down

        # Stop and remove all data
        api-forge-cli dev down --volumes
    """
    details = "This will stop all development Docker Compose services."
    extra_warning = None

    if volumes:
        extra_warning = (
            "⚠️  --volumes flag is set: ALL DATA WILL BE PERMANENTLY DELETED!\n"
            "   This includes databases, caches, and any persistent storage."
        )

    if not console.confirm_action(
        action="Stop development environment",
        details=details,
        extra_warning=extra_warning,
        force=yes,
    ):
        console.print("[dim]Operation cancelled.[/dim]")
        raise typer.Exit(0)

    console.print_header("Stopping Development Environment", style="red")

    try:
        deployer = _get_deployer()
        deployer.teardown(volumes=volumes)
    except DeploymentError as e:
        console.handle_error(f"Teardown failed: {e.message}", e.details)


@app.command()
def status() -> None:
    """📊 Show status of development services.

    Displays the current status of all development services including
    health check results and connection information.

    Examples:
        api-forge-cli dev status
    """
    deployer = _get_deployer()
    deployer.show_status()


@app.command()
def logs(
    service: str = typer.Argument(
        None,
        help="Service name (keycloak, postgres, redis, temporal). Shows all if omitted.",
    ),
    follow: bool = typer.Option(
        False,
        "--follow",
        "-f",
        help="Follow log output",
    ),
    tail: int = typer.Option(
        100,
        "--tail",
        "-n",
        help="Number of lines to show from the end",
    ),
) -> None:
    """📜 View logs from development services.

    Shows logs from Docker Compose services. Specify a service name
    to view logs from a single service.

    Examples:
        # View all logs
        api-forge-cli dev logs

        # View PostgreSQL logs
        api-forge-cli dev logs postgres

        # Follow Keycloak logs
        api-forge-cli dev logs keycloak --follow
    """
    if service:
        # Map friendly names to Docker Compose service names
        service_map = {
            "keycloak": "keycloak",
            "postgres": "postgres",
            "redis": "redis",
            "temporal": "temporal",
            "temporal-ui": "temporal-web",
        }
        compose_service = service_map.get(service.lower(), service)
    else:
        compose_service = None

    try:
        runner = _get_compose_runner()
        runner.logs(service=compose_service, follow=follow, tail=tail)
    except subprocess.CalledProcessError as e:
        console.handle_error(f"Failed to get logs: {e}")
    except KeyboardInterrupt:
        pass  # User cancelled with Ctrl+C


@app.command()
def restart(
    service: str = typer.Argument(
        ...,
        help="Service to restart (keycloak, postgres, redis, temporal)",
    ),
) -> None:
    """🔄 Restart a specific development service.

    Restarts a single service without affecting other services.

    Examples:
        # Restart PostgreSQL
        api-forge-cli dev restart postgres

        # Restart Keycloak
        api-forge-cli dev restart keycloak
    """
    # Map friendly names to Docker Compose service names
    service_map = {
        "keycloak": "keycloak",
        "postgres": "postgres",
        "redis": "redis",
        "temporal": "temporal",
        "temporal-ui": "temporal-web",
    }

    compose_service = service_map.get(service.lower(), service)

    console.print(f"[bold]Restarting {service}...[/bold]")

    try:
        runner = _get_compose_runner()
        runner.restart(service=compose_service)
        console.print(f"[green]✅ {service} restarted successfully[/green]")
    except subprocess.CalledProcessError as e:
        console.handle_error(f"Failed to restart {service}: {e}")
