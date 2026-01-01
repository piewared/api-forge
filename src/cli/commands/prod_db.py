"""PostgreSQL database management for Docker Compose deployments.

This module provides db subcommands under 'prod' for managing PostgreSQL
databases in Docker Compose environments.
"""

import subprocess
import time
from pathlib import Path
from typing import Annotated

import typer

from src.cli.commands.db import (
    DbRuntime,
    get_compose_runtime,
    run_backup,
    run_init,
    run_migrate,
    run_reset,
    run_status,
    run_sync,
    run_verify,
)
from src.cli.commands.db_utils import (
    configure_external_database,
    read_env_example_values,
    update_bundled_postgres_config,
    update_env_file,
)
from src.cli.deployment.status_display import is_temporal_enabled
from src.cli.shared.console import console, with_error_handling
from src.utils.paths import get_project_root


def _get_compose_file() -> Path:
    """Get the docker-compose.prod.yml file path."""
    return get_project_root() / "docker-compose.prod.yml"


def _get_runtime() -> DbRuntime:
    """Return the Docker Compose DB runtime."""
    return get_compose_runtime()


def _run_compose_command(
    args: list[str], capture: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a docker-compose command with the prod compose file."""
    compose_file = _get_compose_file()
    # Use the same fixed project name as ProdDeployer to avoid cross-command
    # network/volume label conflicts (e.g., application_internal).
    cmd = ["docker", "compose", "-p", "api-forge-prod", "-f", str(compose_file)] + args
    if capture:
        return subprocess.run(
            cmd, capture_output=True, text=True, cwd=get_project_root()
        )
    return subprocess.run(cmd, cwd=get_project_root(), capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Typer App
# ---------------------------------------------------------------------------

prod_db_app = typer.Typer(
    name="db",
    help="PostgreSQL database management for Docker Compose.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@prod_db_app.command()
@with_error_handling
def create(
    # Mode selection (mutually exclusive)
    bundled: Annotated[
        bool,
        typer.Option(
            "--bundled",
            help="Deploy bundled PostgreSQL via Docker Compose",
        ),
    ] = False,
    external: Annotated[
        bool,
        typer.Option(
            "--external",
            help="Configure connection to external PostgreSQL",
        ),
    ] = False,
    # External mode parameters
    connection_string: Annotated[
        str | None,
        typer.Option(
            "--connection-string",
            "-c",
            help="Full PostgreSQL connection string (postgres://user:pass@host:port/db)",
        ),
    ] = None,
    host: Annotated[
        str | None,
        typer.Option(
            "--host",
            "-H",
            help="Database host (overrides connection string)",
        ),
    ] = None,
    port: Annotated[
        str | None,
        typer.Option(
            "--port",
            "-P",
            help="Database port (overrides connection string)",
        ),
    ] = None,
    username: Annotated[
        str | None,
        typer.Option(
            "--username",
            "-u",
            help="Database username (overrides connection string)",
        ),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option(
            "--password",
            "-p",
            help="Database password (overrides connection string)",
        ),
    ] = None,
    database: Annotated[
        str | None,
        typer.Option(
            "--database",
            "-d",
            help="Database name (overrides connection string)",
        ),
    ] = None,
    sslmode: Annotated[
        str | None,
        typer.Option(
            "--sslmode",
            help="SSL mode (e.g., require, verify-full)",
        ),
    ] = None,
    tls_ca: Annotated[
        str | None,
        typer.Option(
            "--tls-ca",
            help="Path to TLS CA certificate file for external PostgreSQL (e.g., Aiven CA)",
        ),
    ] = None,
    # Bundled mode parameters
    skip_build: Annotated[
        bool,
        typer.Option(
            "--skip-build",
            help="Skip building the PostgreSQL image (bundled mode only)",
        ),
    ] = False,
    wait: Annotated[
        bool,
        typer.Option(
            "--wait/--no-wait",
            help="Wait for PostgreSQL to be healthy (bundled mode only)",
        ),
    ] = True,
) -> None:
    """Configure PostgreSQL database for Docker Compose deployment.

    Two modes are available:

    --bundled: Deploy a bundled PostgreSQL instance via Docker Compose.
    This builds the PostgreSQL image and starts the container with security settings.

    --external: Configure connection to an external PostgreSQL instance (e.g., Aiven, RDS).
    This updates .env and config.yaml with connection details.

    Examples:
        # Deploy bundled PostgreSQL
        uv run api-forge-cli prod db create --bundled
        uv run api-forge-cli prod db create --bundled --skip-build

        # Configure external PostgreSQL with connection string
        uv run api-forge-cli prod db create --external \\
            --connection-string "postgres://admin:secret@db.example.com:5432/mydb?sslmode=require"

        # Configure external PostgreSQL with individual parameters
        uv run api-forge-cli prod db create --external \\
            --host db.example.com --port 5432 \\
            --username admin --password secret --database mydb

        # Mix: connection string with override
        uv run api-forge-cli prod db create --external \\
            --connection-string "postgres://user:pass@host:5432/db" \\
            --password new-secret  # Override password from connection string
    """
    # Validate mode selection
    if bundled and external:
        console.print("[red]❌ Cannot use both --bundled and --external[/red]")
        raise typer.Exit(1)

    if not bundled and not external:
        console.print("[red]❌ Must specify either --bundled or --external[/red]")
        console.print(
            "[dim]Use --bundled to deploy PostgreSQL via Docker Compose[/dim]"
        )
        console.print("[dim]Use --external to configure an external database[/dim]")
        raise typer.Exit(1)

    if external:
        configure_external_database(
            connection_string=connection_string,
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            sslmode=sslmode,
            tls_ca=tls_ca,
            next_steps_cmd_prefix="prod",
        )
    else:
        _create_bundled(skip_build=skip_build, wait=wait)


def _create_bundled(*, skip_build: bool, wait: bool) -> None:
    """Create and start the bundled PostgreSQL container."""
    console.print_header("Creating PostgreSQL Container (Docker Compose)")

    # If a previous run created the shared network under a different compose project
    # name, Docker Compose will error with a label mismatch.
    # We proactively remove that stale network so this command can proceed.
    network_name = "application_internal"
    expected_project = "api-forge-prod"
    inspect = subprocess.run(
        [
            "docker",
            "network",
            "inspect",
            network_name,
            "--format",
            '{{ index .Labels "com.docker.compose.project" }}',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if inspect.returncode == 0:
        existing_project = (inspect.stdout or "").strip()
        if existing_project and existing_project != expected_project:
            console.print(
                f"[yellow]⚠ Removing stale network '{network_name}' from compose project '{existing_project}'[/yellow]"
            )
            subprocess.run(
                ["docker", "network", "rm", network_name],
                capture_output=True,
                text=True,
                check=False,
            )

    compose_file = _get_compose_file()
    if not compose_file.exists():
        console.error("docker-compose.prod.yml not found")
        raise typer.Exit(1)

    # Ensure data directories exist before starting container
    from src.cli.deployment.prod_deployer import ProdDeployer

    deployer = ProdDeployer(console, get_project_root())
    deployer._ensure_required_directories()

    # Read bundled defaults from .env.example
    bundled_keys = ["PRODUCTION_DATABASE_URL", "PG_SUPERUSER", "PG_DB"]
    bundled_defaults = read_env_example_values(bundled_keys)

    if not bundled_defaults:
        console.print("[red]❌ Could not read bundled defaults from .env.example[/red]")
        raise typer.Exit(1)

    # Update .env with bundled defaults from .env.example
    console.info("Updating .env file for bundled PostgreSQL...")
    update_env_file(bundled_defaults)
    console.ok(".env file updated")

    # Update config.yaml
    console.info("Updating config.yaml...")
    update_bundled_postgres_config(enabled=True)
    console.ok("config.yaml updated (bundled_postgres.enabled=true)")

    # Check if container already exists (exact name match)
    check_result = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=^api-forge-postgres$",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
    )
    container_exists = check_result.stdout.strip() == "api-forge-postgres"

    if container_exists:
        console.info(
            "Container 'api-forge-postgres' already exists, checking status..."
        )
        status_result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}}",
                "api-forge-postgres",
            ],
            capture_output=True,
            text=True,
        )

        if status_result.returncode != 0:
            console.error(
                f"Failed to inspect container (it may have been removed):\n{status_result.stderr}"
            )
            console.info("Recreating container...")
            # Fall through to creation logic below
            container_exists = False
        else:
            status = status_result.stdout.strip()

            if status == "running":
                console.print("[yellow]⚠️  Container is already running[/yellow]")
                console.print(
                    "[dim]Use 'uv run api-forge-cli prod db status' to check health[/dim]"
                )
                return
            else:
                console.info(f"Container status: {status}, starting it...")
                # Use docker start for existing containers instead of compose up
                result = subprocess.run(
                    ["docker", "start", "api-forge-postgres"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    console.error(
                        f"Failed to start PostgreSQL container:\n{result.stderr}"
                    )
                    raise typer.Exit(1)

    if not container_exists:
        # Build image if needed
        if not skip_build:
            console.info("Building PostgreSQL image...")
            result = _run_compose_command(["build", "postgres"])
            if result.returncode != 0:
                console.error(f"Failed to build PostgreSQL image:\n{result.stderr}")
                raise typer.Exit(1)
            console.ok("PostgreSQL image built")

        # Start postgres with profile
        console.info("Starting PostgreSQL container...")
        result = _run_compose_command(["--profile", "postgres", "up", "-d", "postgres"])
        if result.returncode != 0:
            console.error(f"Failed to start PostgreSQL container:\n{result.stderr}")
            raise typer.Exit(1)

    # Wait for health check
    if wait:
        console.info("Waiting for PostgreSQL to be healthy...")
        max_wait = 60
        start = time.time()

        while time.time() - start < max_wait:
            result = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Health.Status}}",
                    "api-forge-postgres",
                ],
                capture_output=True,
                text=True,
            )
            health = result.stdout.strip()
            if health == "healthy":
                console.ok("PostgreSQL is healthy")
                break
            elif health == "unhealthy":
                console.error("PostgreSQL is unhealthy")
                raise typer.Exit(1)
            time.sleep(2)
        else:
            console.error("Timed out waiting for PostgreSQL")
            raise typer.Exit(1)

    console.print("\n[bold green]🎉 PostgreSQL container created![/bold green]")

    # Auto-initialize database after successful deployment
    console.info("\nInitializing database...")

    try:
        success = run_init(_get_runtime())
        if not success:
            console.error("Database initialization failed")
            console.print("\n[dim]You can retry with:[/dim]")
            console.print("  uv run api-forge-cli prod db init")
            raise typer.Exit(1)

        console.ok("Database initialized successfully")

    except Exception as e:
        console.error(f"Database initialization failed: {e}")
        console.print("\n[dim]You can retry with:[/dim]")
        console.print("  uv run api-forge-cli prod db init")
        raise typer.Exit(1) from e
    console.print("\n[dim]Next steps:[/dim]")
    console.print("  - Run 'uv run api-forge-cli prod db verify' to verify setup")


@prod_db_app.command(name="init")
@with_error_handling
def init_db() -> None:
    """Initialize the PostgreSQL database with roles and schema.

    This command:
    - Creates the owner, app user, and read-only roles
    - Creates the application database
    - Sets up the schema with proper privileges

    Credentials are prompted at runtime (never stored in files).

    Examples:
        uv run api-forge-cli prod db init
        uv run api-forge-cli prod db init --temporal
    """
    console.print_header("Initializing PostgreSQL Database (Docker Compose)")
    success = run_init(_get_runtime())

    if not success:
        raise typer.Exit(1)


@prod_db_app.command()
@with_error_handling
def verify() -> None:
    """Verify PostgreSQL database setup and configuration.

    This command checks:
    - Role existence and attributes
    - Database and schema ownership
    - Table and sequence privileges
    - TLS configuration
    - Temporal roles (if enabled)

    Examples:
        uv run api-forge-cli prod db verify
    """
    console.print_header("Verifying PostgreSQL Configuration (Docker Compose)")
    success = run_verify(_get_runtime(), superuser_mode=False)

    if not success:
        console.info(
            'Please run "uv run api-forge-cli prod db init" to re-initialize the database.'
        )
        raise typer.Exit(1)


@prod_db_app.command()
@with_error_handling
def sync() -> None:
    """Synchronize PostgreSQL role passwords.

    This command updates database role passwords to match new values.
    Use after rotating secrets to sync the new passwords to the database.

    Credentials are prompted at runtime.

    Examples:
        uv run api-forge-cli prod db sync
        uv run api-forge-cli prod db sync --temporal
    """
    console.print_header("Synchronizing PostgreSQL Passwords (Docker Compose)")
    success = run_sync(_get_runtime())

    if not success:
        raise typer.Exit(1)


@prod_db_app.command()
@with_error_handling
def backup(
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory for backup files",
        ),
    ] = None,
) -> None:
    """Create a PostgreSQL database backup.

    Creates both custom format (.dump) and compressed SQL (.sql.gz) backups
    with SHA256 checksums. Uses the read-only user for backups.

    Examples:
        uv run api-forge-cli prod db backup
        uv run api-forge-cli prod db backup --output-dir ./backups
    """
    console.print_header("Creating PostgreSQL Backup (Docker Compose)")
    backup_dir = output_dir or Path("./data/postgres-backups")
    success, result = run_backup(
        _get_runtime(),
        output_dir=backup_dir,
        superuser_mode=False,
    )

    if not success:
        console.error(f"Backup failed: {result}")
        raise typer.Exit(1)

    console.print(f"\n[bold green]🎉 Backup created: {result}[/bold green]")


@prod_db_app.command()
@with_error_handling
def reset(
    include_temporal: Annotated[
        bool,
        typer.Option(
            "--temporal/--no-temporal",
            help="Also drop Temporal databases and roles",
        ),
    ] = True,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip confirmation prompt",
        ),
    ] = False,
) -> None:
    """Reset the PostgreSQL database to clean state (DESTRUCTIVE).

    This command drops all application-created databases, roles, and schemas,
    returning PostgreSQL to a clean state ready for re-initialization.

    Drops:
    - Application database (appdb)
    - Application roles (appuser, appowner, backupuser)
    - Temporal databases and roles (if --temporal, default)

    Does NOT affect:
    - Docker containers (use 'prod down' to stop containers)
    - Docker volumes (use 'prod down --volumes' to remove volumes)
    - System databases (postgres, template0, template1)

    WARNING: This will permanently delete all database data!

    Examples:
        uv run api-forge-cli prod db reset
        uv run api-forge-cli prod db reset --no-temporal  # Keep Temporal data
        uv run api-forge-cli prod db reset -y             # Skip confirmation
    """
    console.print_header("Resetting PostgreSQL Database (Docker Compose)")

    include_temporal = is_temporal_enabled() and include_temporal

    if not yes:
        if not console.confirm_action(
            "Reset PostgreSQL database",
            "This will permanently delete all database data including:\n"
            "  • All application databases\n"
            "  • All application roles\n"
            "  • All tables and data\n"
            + ("  • Temporal databases and roles\n" if include_temporal else ""),
        ):
            console.print("[dim]Operation cancelled[/dim]")
            raise typer.Exit(0)

    success = run_reset(
        _get_runtime(),
        include_temporal=include_temporal,
        superuser_mode=False,
    )

    if not success:
        raise typer.Exit(1)

    console.print("\n[bold green]🎉 PostgreSQL database reset complete![/bold green]")
    console.print("\n[dim]To re-initialize:[/dim]")
    console.print("  Run 'uv run api-forge-cli prod db init'")


@prod_db_app.command()
@with_error_handling
def status() -> None:
    """Show PostgreSQL health and performance metrics.

    Displays runtime metrics including:
    - Connection latency and active connections
    - Database sizes and row counts
    - Cache hit ratios
    - Database uptime

    Works with both bundled Docker Compose PostgreSQL and external databases.

    Examples:
        uv run api-forge-cli prod db status
    """
    console.print_header("PostgreSQL Health & Performance")
    run_status(_get_runtime(), superuser_mode=False)


@prod_db_app.command()
@with_error_handling
def migrate(
    action: Annotated[
        str,
        typer.Argument(
            help=(
                "Migration action: upgrade, downgrade, current, history, revision, "
                "heads, merge, show, stamp"
            )
        ),
    ],
    revision: Annotated[
        str | None,
        typer.Argument(
            help="Target revision (for downgrade) or message (for revision)"
        ),
    ] = None,
    message: Annotated[
        str | None,
        typer.Option(
            "--message",
            "-m",
            help=(
                "Optional message (used by merge). If omitted, merge will use the second "
                "argument as the message when provided, otherwise a default."
            ),
        ),
    ] = None,
    merge_revisions: Annotated[
        list[str] | None,
        typer.Option(
            "--merge-revision",
            "-r",
            help=(
                "Revision(s) to merge (for merge). Can be provided multiple times. "
                "If omitted, merges all current heads."
            ),
        ),
    ] = None,
    purge: Annotated[
        bool,
        typer.Option(
            "--purge",
            help=(
                "For stamp only: purge the version table before stamping. "
                "Use with extreme care."
            ),
        ),
    ] = False,
    autogenerate: Annotated[
        bool,
        typer.Option(
            "--autogenerate/--no-autogenerate",
            help="Autogenerate migration from model changes (for revision)",
        ),
    ] = True,
    sql: Annotated[
        bool,
        typer.Option(
            "--sql",
            help="Generate SQL output instead of running migration",
        ),
    ] = False,
) -> None:
    """Manage database schema migrations with Alembic.

    Actions:
        upgrade [revision]  - Apply migrations up to revision (default: head)
        downgrade <revision> - Rollback to a specific revision
        current            - Show current migration revision
        history            - Show migration history
        revision <message> - Create a new migration (with --autogenerate)
        heads              - Show current head revision(s)
        merge              - Create a merge migration (default: merge all heads)
        show <revision>    - Show a specific migration's details
        stamp <revision>   - Set DB revision without running migrations

    Examples:
        # Apply all pending migrations
        uv run api-forge-cli prod db migrate upgrade

        # Apply migrations up to a specific revision
        uv run api-forge-cli prod db migrate upgrade abc123

        # Rollback to a specific revision
        uv run api-forge-cli prod db migrate downgrade abc123

        # Rollback one migration
        uv run api-forge-cli prod db migrate downgrade -1

        # Show current migration state
        uv run api-forge-cli prod db migrate current

        # Show migration history
        uv run api-forge-cli prod db migrate history

        # Create a new migration with autogeneration
        uv run api-forge-cli prod db migrate revision "add user table"

        # Create empty migration template
        uv run api-forge-cli prod db migrate revision "custom migration" --no-autogenerate

        # Generate SQL for upgrade without running it
        uv run api-forge-cli prod db migrate upgrade --sql

        # Show current heads (useful when multiple heads exist)
        uv run api-forge-cli prod db migrate heads

        # Merge all current heads
        uv run api-forge-cli prod db migrate merge --message "merge heads"

        # Merge specific revisions
        uv run api-forge-cli prod db migrate merge --message "merge" \
            -r abc123 -r def456

        # Show a specific revision
        uv run api-forge-cli prod db migrate show 19becf30b774

        # Stamp the DB to a revision (no migration execution)
        uv run api-forge-cli prod db migrate stamp head
    """
    merge_revisions_normalized: list[str] = merge_revisions or []

    run_migrate(
        _get_runtime(),
        action=action,
        revision=revision,
        message=message,
        merge_revisions=merge_revisions_normalized,
        purge=purge,
        autogenerate=autogenerate,
        sql=sql,
    )
