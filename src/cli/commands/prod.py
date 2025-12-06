"""Production Docker Compose environment commands.

This module provides commands for managing the production Docker Compose
environment: starting services, stopping them, and checking status.
"""

from typing import TYPE_CHECKING, Annotated

import typer

from .shared import (
    confirm_action,
    console,
    get_project_root,
    handle_error,
    print_header,
    with_error_handling,
)

if TYPE_CHECKING:
    from src.cli.deployment.prod_deployer import ProdDeployer


# ---------------------------------------------------------------------------
# Deployer Factory
# ---------------------------------------------------------------------------


def _get_deployer() -> "ProdDeployer":
    """Get the production deployer instance.

    Returns:
        ProdDeployer instance configured for current project
    """
    from src.cli.deployment.prod_deployer import ProdDeployer

    return ProdDeployer(console, get_project_root())


# ---------------------------------------------------------------------------
# Typer App
# ---------------------------------------------------------------------------

prod_app = typer.Typer(
    name="prod",
    help="Production Docker Compose environment commands.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@prod_app.command()
@with_error_handling
def up(
    skip_build: Annotated[
        bool,
        typer.Option(
            "--skip-build",
            help="Skip building the application image",
        ),
    ] = False,
    no_wait: Annotated[
        bool,
        typer.Option(
            "--no-wait",
            help="Don't wait for health checks to complete",
        ),
    ] = False,
    force_recreate: Annotated[
        bool,
        typer.Option(
            "--force-recreate",
            help="Force recreate containers (useful for secret rotation)",
        ),
    ] = False,
) -> None:
    """Start the production Docker Compose environment.

    This command:
    - Ensures required data directories exist
    - Validates and cleans up stale bind-mount volumes
    - Builds the application Docker image (unless --skip-build)
    - Starts all production services with health checks
    - Monitors service health (unless --no-wait)

    Examples:
        uv run api-forge-cli prod up
        uv run api-forge-cli prod up --skip-build --no-wait
        uv run api-forge-cli prod up --force-recreate  # For secret rotation
    """
    print_header("Starting Production Environment")

    deployer = _get_deployer()
    deployer.deploy(
        skip_build=skip_build,
        no_wait=no_wait,
        force_recreate=force_recreate,
    )


@prod_app.command()
@with_error_handling
def down(
    volumes: Annotated[
        bool,
        typer.Option(
            "--volumes",
            "-v",
            help="Also remove data volumes and directories (DESTRUCTIVE)",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip confirmation prompt for destructive operations",
        ),
    ] = False,
) -> None:
    """Stop the production Docker Compose environment.

    By default, this preserves all data volumes so you can restart later
    without losing data. Use --volumes to also remove data (requires confirmation).

    Examples:
        uv run api-forge-cli prod down
        uv run api-forge-cli prod down --volumes  # Remove data too
        uv run api-forge-cli prod down -v -y      # Remove data without prompt
    """
    print_header("Stopping Production Environment")

    if volumes and not yes:
        if not confirm_action(
            "Remove data volumes",
            "This will permanently delete all production data including:\n"
            "  • PostgreSQL database\n"
            "  • Redis cache and sessions\n"
            "  • Application logs\n"
            "  • SSL certificates",
        ):
            console.print("[dim]Operation cancelled[/dim]")
            raise typer.Exit(0)

    deployer = _get_deployer()
    deployer.teardown(volumes=volumes)


@prod_app.command()
@with_error_handling
def status() -> None:
    """Show the status of production services.

    Displays the health and configuration of each production service.

    Examples:
        uv run api-forge-cli prod status
    """
    print_header("Production Environment Status")

    deployer = _get_deployer()
    deployer.show_status()


@prod_app.command()
@with_error_handling
def logs(
    service: Annotated[
        str | None,
        typer.Argument(
            help="Service name to view logs for (e.g., app, postgres, redis, temporal)",
        ),
    ] = None,
    follow: Annotated[
        bool,
        typer.Option(
            "--follow",
            "-f",
            help="Follow log output",
        ),
    ] = False,
    tail: Annotated[
        int,
        typer.Option(
            "--tail",
            "-n",
            help="Number of lines to show from the end of the logs",
        ),
    ] = 100,
) -> None:
    """View logs from production services.

    Shows logs from the production Docker Compose environment. Optionally
    specify a service name to filter logs.

    Examples:
        uv run api-forge-cli prod logs           # All services
        uv run api-forge-cli prod logs app       # Just the app service
        uv run api-forge-cli prod logs app -f    # Follow app logs
        uv run api-forge-cli prod logs -n 50     # Last 50 lines
    """
    import subprocess

    project_root = get_project_root()
    compose_file = project_root / "docker-compose.prod.yml"

    if not compose_file.exists():
        handle_error(f"Compose file not found: {compose_file}")
        raise typer.Exit(1)

    cmd = [
        "docker",
        "compose",
        "-p",
        "api-forge-prod",
        "-f",
        str(compose_file),
        "logs",
        f"--tail={tail}",
    ]

    if follow:
        cmd.append("--follow")

    if service:
        cmd.append(service)
        console.print(f"[dim]Showing logs for service: {service}[/dim]\n")
    else:
        console.print("[dim]Showing logs for all production services[/dim]\n")

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        handle_error(f"Failed to retrieve logs: {e}")
        raise typer.Exit(1) from e
    except KeyboardInterrupt:
        console.print("\n[dim]Log streaming stopped[/dim]")


@prod_app.command()
@with_error_handling
def restart(
    service: Annotated[
        str | None,
        typer.Argument(
            help="Service name to restart (restarts all if not specified)",
        ),
    ] = None,
    force_recreate: Annotated[
        bool,
        typer.Option(
            "--force-recreate",
            help="Force recreate containers",
        ),
    ] = False,
) -> None:
    """Restart production services.

    Restarts one or all production services. Useful for picking up
    configuration changes.

    Examples:
        uv run api-forge-cli prod restart          # Restart all
        uv run api-forge-cli prod restart app      # Just restart app
        uv run api-forge-cli prod restart --force-recreate
    """
    import subprocess

    project_root = get_project_root()
    compose_file = project_root / "docker-compose.prod.yml"

    if not compose_file.exists():
        handle_error(f"Compose file not found: {compose_file}")
        raise typer.Exit(1)

    if service:
        console.print(f"[cyan]Restarting service: {service}[/cyan]")
        cmd = [
            "docker",
            "compose",
            "-p",
            "api-forge-prod",
            "-f",
            str(compose_file),
            "restart",
            service,
        ]
    elif force_recreate:
        # Full restart with force-recreate
        console.print("[cyan]Force restarting all production services...[/cyan]")
        cmd = [
            "docker",
            "compose",
            "-p",
            "api-forge-prod",
            "-f",
            str(compose_file),
            "up",
            "-d",
            "--force-recreate",
        ]
    else:
        console.print("[cyan]Restarting all production services...[/cyan]")
        cmd = [
            "docker",
            "compose",
            "-p",
            "api-forge-prod",
            "-f",
            str(compose_file),
            "restart",
        ]

    try:
        subprocess.run(cmd, check=True)
        console.print("[green]✓[/green] Restart complete")
    except subprocess.CalledProcessError as e:
        handle_error(f"Failed to restart services: {e}")
        raise typer.Exit(1) from e


@prod_app.command()
@with_error_handling
def build(
    service: Annotated[
        str | None,
        typer.Argument(
            help="Service name to build (builds all if not specified)",
        ),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache",
            help="Build without using cache",
        ),
    ] = False,
) -> None:
    """Build production Docker images.

    Builds one or all production service images. Useful for rebuilding
    after Dockerfile changes.

    Examples:
        uv run api-forge-cli prod build           # Build all
        uv run api-forge-cli prod build app       # Just build app
        uv run api-forge-cli prod build --no-cache
    """
    import subprocess

    project_root = get_project_root()
    compose_file = project_root / "docker-compose.prod.yml"

    if not compose_file.exists():
        handle_error(f"Compose file not found: {compose_file}")
        raise typer.Exit(1)

    cmd = [
        "docker",
        "compose",
        "-p",
        "api-forge-prod",
        "-f",
        str(compose_file),
        "build",
    ]

    if no_cache:
        cmd.append("--no-cache")

    if service:
        cmd.append(service)
        console.print(f"[cyan]Building service: {service}[/cyan]")
    else:
        console.print("[cyan]Building all production images...[/cyan]")

    try:
        subprocess.run(cmd, check=True)
        console.print("[green]✓[/green] Build complete")
    except subprocess.CalledProcessError as e:
        handle_error(f"Build failed: {e}")
        raise typer.Exit(1) from e
