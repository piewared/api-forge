"""Production Docker Compose environment commands.

This module provides commands for managing the production Docker Compose
environment: starting services, stopping them, and checking status.
"""

import subprocess
from typing import TYPE_CHECKING, Annotated

import typer

from src.cli.shared.compose import ComposeRunner
from src.cli.shared.console import console, with_error_handling
from src.infra.postgres.connection import get_settings
from src.utils.paths import get_project_root

from .prod_db import prod_db_app

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


def _get_compose_runner() -> ComposeRunner:
    """Create a ComposeRunner for the prod compose file."""
    project_root = get_project_root()
    return ComposeRunner(
        project_root,
        compose_file=project_root / "docker-compose.prod.yml",
        project_name="api-forge-prod",
    )


def _verify_database_accessible() -> bool:
    """Verify PostgreSQL database is accessible.

    Attempts to connect to the database and run a simple query.
    Returns True if successful, False otherwise.
    """
    try:
        from src.infra.docker_compose.postgres_connection import (
            get_docker_compose_postgres_connection,
        )

        settings = get_settings()
        conn = get_docker_compose_postgres_connection(settings)

        # Test connection with a short timeout
        success, msg = conn.test_connection()

        if success:
            console.ok(f"Database accessible: {msg[:60]}...")
        else:
            console.error(f"Database check failed: {msg}")

        return success

    except ImportError:
        # psycopg not installed, skip check
        console.warn("Database check skipped (psycopg not installed)")
        return True
    except Exception as e:
        console.error(f"Database check failed: {e}")
        return False


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
    skip_db_check: Annotated[
        bool,
        typer.Option(
            "--skip-db-check",
            help="Skip PostgreSQL verification before deployment",
        ),
    ] = False,
) -> None:
    """Start the production Docker Compose environment.

    This command:
    - Verifies PostgreSQL is accessible (unless --skip-db-check)
    - Ensures required data directories exist
    - Validates and cleans up stale bind-mount volumes
    - Builds the application Docker image (unless --skip-build)
    - Starts all production services with health checks
    - Monitors service health (unless --no-wait)

    Examples:
        uv run api-forge-cli prod up
        uv run api-forge-cli prod up --skip-build --no-wait
        uv run api-forge-cli prod up --force-recreate  # For secret rotation
        uv run api-forge-cli prod up --skip-db-check   # Skip database verification
    """
    from src.infra.utils.service_config import is_bundled_postgres_enabled

    console.print_header("Starting Production Environment")

    # Verify database is accessible before deploying
    if not skip_db_check:
        if not _verify_database_accessible():
            console.error("Database verification failed.")
            console.print(
                "[dim]Please ensure PostgreSQL is running and accessible.[/dim]\n"
            )
            if is_bundled_postgres_enabled():
                console.print(
                    "[dim]For bundled PostgreSQL, run:[/dim]\n"
                    "  uv run api-forge-cli db create\n"
                    "  uv run api-forge-cli db init\n"
                )
            else:
                console.print(
                    "[dim]For external PostgreSQL, verify DATABASE_URL in .env[/dim]\n"
                )
            console.print("[dim]Use --skip-db-check to bypass this verification.[/dim]")
            raise typer.Exit(1)

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
    console.print_header("Stopping Production Environment")

    if volumes and not yes:
        if not console.confirm_action(
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
    console.print_header("Production Environment Status")

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
    project_root = get_project_root()
    compose_file = project_root / "docker-compose.prod.yml"

    if not compose_file.exists():
        console.handle_error(f"Compose file not found: {compose_file}")
        raise typer.Exit(1)

    if service:
        console.print(f"[dim]Showing logs for service: {service}[/dim]\n")
    else:
        console.print("[dim]Showing logs for all production services[/dim]\n")

    try:
        runner = _get_compose_runner()
        runner.logs(service=service, follow=follow, tail=tail)
    except subprocess.CalledProcessError as e:
        console.handle_error(f"Failed to retrieve logs: {e}")
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
    project_root = get_project_root()
    compose_file = project_root / "docker-compose.prod.yml"

    if not compose_file.exists():
        console.handle_error(f"Compose file not found: {compose_file}")

    if service:
        console.info(f"Restarting service: {service}")
    elif force_recreate:
        # Full restart with force-recreate
        console.info("Force restarting all production services...")
    else:
        console.info("Restarting all production services...")

    try:
        runner = _get_compose_runner()
        if force_recreate and not service:
            runner.run(["up", "-d", "--force-recreate"], check=True)
        else:
            runner.restart(service=service)
        console.ok("Restart complete")
    except subprocess.CalledProcessError as e:
        console.handle_error(f"Failed to restart services: {e}")


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
    project_root = get_project_root()
    compose_file = project_root / "docker-compose.prod.yml"

    if not compose_file.exists():
        console.handle_error(f"Compose file not found: {compose_file}")

    if service:
        console.info(f"Building service: {service}")
    else:
        console.info("Building all production images...")

    try:
        runner = _get_compose_runner()
        runner.build(service=service, no_cache=no_cache)
        console.ok("Build complete")
    except subprocess.CalledProcessError as e:
        console.handle_error(f"Build failed: {e}")


# ---------------------------------------------------------------------------
# Register Subcommands
# ---------------------------------------------------------------------------

prod_app.add_typer(prod_db_app, name="db")
