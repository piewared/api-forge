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

from pathlib import Path

import typer

from src.cli.deployment import DevDeployer
from src.cli.deployment.helm_deployer.image_builder import DeploymentError

from .shared import (
    confirm_action,
    console,
    get_project_root,
    handle_error,
    print_header,
)

# Create the dev command group
app = typer.Typer(
    name="dev",
    help="🔧 Development environment commands (Docker Compose)",
    no_args_is_help=True,
)


def _get_deployer() -> DevDeployer:
    """Create a DevDeployer instance with current project context."""
    return DevDeployer(console, Path(get_project_root()))


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
    print_header("Starting Development Environment")

    try:
        deployer = _get_deployer()
        deployer.deploy(force=force, no_wait=no_wait, start_server=start_server)
    except DeploymentError as e:
        handle_error(f"Deployment failed: {e.message}", e.details)


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

    if not confirm_action(
        action="Stop development environment",
        details=details,
        extra_warning=extra_warning,
        force=yes,
    ):
        console.print("[dim]Operation cancelled.[/dim]")
        raise typer.Exit(0)

    print_header("Stopping Development Environment", style="red")

    try:
        deployer = _get_deployer()
        deployer.teardown(volumes=volumes)
    except DeploymentError as e:
        handle_error(f"Teardown failed: {e.message}", e.details)


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
    import subprocess

    compose_file = "docker-compose.dev.yml"
    cmd = ["docker", "compose", "-f", compose_file, "logs"]

    if tail:
        cmd.extend(["--tail", str(tail)])

    if follow:
        cmd.append("--follow")

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
        cmd.append(compose_service)

    try:
        subprocess.run(cmd, cwd=get_project_root(), check=True)
    except subprocess.CalledProcessError as e:
        handle_error(f"Failed to get logs: {e}")
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
    import subprocess

    compose_file = "docker-compose.dev.yml"

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

    cmd = ["docker", "compose", "-f", compose_file, "restart", compose_service]

    try:
        subprocess.run(cmd, cwd=get_project_root(), check=True)
        console.print(f"[green]✅ {service} restarted successfully[/green]")
    except subprocess.CalledProcessError as e:
        handle_error(f"Failed to restart {service}: {e}")
