"""Fly Postgres workflow commands (init, verify, sync, backup, reset, migrate).

These are thin CLI wrappers that delegate to db/workflows.py via the Fly runtime.
"""

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from src.cli.commands.db import (
    run_backup,
    run_migrate,
    run_reset,
    run_status,
)
from src.cli.commands.db.cli_helpers import execute_init, execute_verify
from src.cli.commands.fly._prereq import check_prerequisites, get_fly_controller
from src.cli.shared.console import console, with_error_handling

from . import fly_db_app
from .select import _select_cluster
from .settings import _get_runtime


@fly_db_app.command()
@with_error_handling
def status(
    cluster: Annotated[
        str | None,
        typer.Option("--cluster", "-c", help="Cluster ID or name"),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Organization filter"),
    ] = None,
) -> None:
    """Show Fly Postgres database status.

    Displays cluster information and database metrics.
    Uses fly proxy to connect to the cluster from your local machine.
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("Fly Postgres Status")

    cluster_info = _select_cluster(controller, cluster, org=org)

    # Display cluster info
    table = Table(title=f"Cluster: {cluster_info.name}", show_header=False)
    table.add_column("Property", style="dim")
    table.add_column("Value")

    table.add_row("ID", cluster_info.id)
    table.add_row("Name", cluster_info.name)
    table.add_row("Region", cluster_info.region)
    table.add_row("Plan", cluster_info.plan)

    status_color = "green" if cluster_info.status == "running" else "yellow"
    table.add_row("Status", f"[{status_color}]{cluster_info.status}[/{status_color}]")

    if cluster_info.created_at:
        table.add_row("Created", cluster_info.created_at)

    console.print(table)

    # Try to get connection and run status check
    if cluster_info.status == "running":
        console.print()
        console.info("Connecting to database for metrics (via fly proxy)...")

        # Pass cluster ID to runtime so it can set up the fly proxy tunnel
        runtime = _get_runtime(cluster_info.id, legacy=cluster_info.is_legacy)
        try:
            run_status(runtime, superuser_mode=True)
        except Exception as e:
            console.warn(f"Could not connect to database: {e}")


@fly_db_app.command()
@with_error_handling
def init(
    cluster: Annotated[
        str | None,
        typer.Option("--cluster", "-c", help="Cluster ID or name"),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Organization filter"),
    ] = None,
) -> None:
    """Initialize database with roles and schema.

    Creates application database users, roles, and runs initial schema setup.
    Uses fly proxy to connect to the cluster from your local machine.
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    cluster_info = _select_cluster(controller, cluster, org=org)
    console.info(f"Initializing cluster: {cluster_info.name} (ID: {cluster_info.id})")

    runtime = _get_runtime(cluster_info.id, legacy=cluster_info.is_legacy)
    execute_init(runtime, label=f"Fly Postgres / {cluster_info.name}")


@fly_db_app.command()
@with_error_handling
def verify(
    cluster: Annotated[
        str | None,
        typer.Option("--cluster", "-c", help="Cluster ID or name"),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Organization filter"),
    ] = None,
    superuser: Annotated[
        bool,
        typer.Option("--superuser", "-s", help="Connect as superuser"),
    ] = False,
) -> None:
    """Verify database setup and configuration.

    Checks that roles, permissions, and schema are correctly configured.
    Uses fly proxy to connect to the cluster from your local machine.
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    cluster_info = _select_cluster(controller, cluster, org=org)
    console.info(f"Verifying cluster: {cluster_info.name} (ID: {cluster_info.id})")

    runtime = _get_runtime(cluster_info.id, legacy=cluster_info.is_legacy)
    execute_verify(
        runtime,
        label=f"Fly Postgres / {cluster_info.name}",
        superuser_mode=superuser,
    )


@fly_db_app.command()
@with_error_handling
def sync(
    cluster: Annotated[
        str | None,
        typer.Option("--cluster", "-c", help="Cluster ID or name"),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Organization filter"),
    ] = None,
) -> None:
    """Synchronize PostgreSQL role passwords.

    Retrieves the current superuser password from Fly, connects to the database,
    and updates all application role passwords to match local secret files.

    For unmanaged postgres: local secrets -> DB -> Fly secrets
    For managed postgres: local secrets -> DB, Fly superuser -> local file
    """
    from src.cli.commands.fly.db_runtime import run_sync_fly
    from src.infra.flyio.db_settings import FlyDbSettings as InfraFlyDbSettings

    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("Sync Fly Postgres Passwords")

    cluster_info = _select_cluster(controller, cluster, org=org)
    console.info(f"Syncing cluster: {cluster_info.name} (ID: {cluster_info.id})")

    runtime = _get_runtime(cluster_info.id, legacy=cluster_info.is_legacy)
    settings = runtime.get_settings()

    if not isinstance(settings, InfraFlyDbSettings):
        console.error("Internal error: Expected FlyDbSettings from Fly runtime")
        raise typer.Exit(1)

    success = run_sync_fly(
        runtime=runtime,
        settings=settings,
        cluster_id=cluster_info.id,
        legacy=cluster_info.is_legacy,
        controller=controller,
    )

    if not success:
        console.error("Password sync failed")
        raise typer.Exit(1)


@fly_db_app.command()
@with_error_handling
def backup(
    cluster: Annotated[
        str | None,
        typer.Option("--cluster", "-c", help="Cluster ID or name"),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Organization filter"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-O", help="Output directory for backup file"),
    ] = None,
    use_mpg_backup: Annotated[
        bool,
        typer.Option(
            "--mpg-backup", help="Use Fly MPG built-in backup instead of pg_dump"
        ),
    ] = False,
) -> None:
    """Create a database backup.

    By default uses pg_dump for a local backup file.
    Use --mpg-backup to trigger Fly's built-in backup system.
    Uses fly proxy to connect to the cluster from your local machine.
    """
    from src.utils.paths import get_project_root

    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("Backup Fly Postgres Database")

    cluster_info = _select_cluster(controller, cluster, org=org)
    console.info(f"Backing up cluster: {cluster_info.name} (ID: {cluster_info.id})")

    if use_mpg_backup:
        # Use Fly's built-in backup
        result = controller.mpg_backup_create(cluster_info.id)
        if result.success:
            console.ok("Backup initiated via Fly MPG")
            console.info(
                "Check backup status: api-forge-cli fly db backup-list --cluster "
                + cluster_info.name
            )
        else:
            console.error("Failed to create backup")
            if result.stderr:
                console.print(f"[dim]{result.stderr}[/dim]")
            raise typer.Exit(1)
    else:
        # Use pg_dump via runtime
        output_dir = output or (get_project_root() / "data" / "postgres-backups")
        output_dir.mkdir(parents=True, exist_ok=True)

        runtime = _get_runtime(cluster_info.id, legacy=cluster_info.is_legacy)

        success, backup_file = run_backup(
            runtime, output_dir=output_dir, superuser_mode=True
        )

        if success:
            console.ok(f"Backup created: {backup_file}")
        else:
            console.error("Backup failed")
            raise typer.Exit(1)


@fly_db_app.command(name="backup-list")
@with_error_handling
def backup_list(
    cluster: Annotated[
        str | None,
        typer.Option("--cluster", "-c", help="Cluster ID or name"),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Organization filter"),
    ] = None,
) -> None:
    """List Fly MPG backups for a cluster."""
    from rich.table import Table

    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("Fly Postgres Backups")

    cluster_info = _select_cluster(controller, cluster, org=org)

    backups = controller.mpg_backup_list(cluster_info.id)

    if not backups:
        console.info(f"No backups found for cluster: {cluster_info.name}")
        return

    table = Table(title=f"Backups for {cluster_info.name}")
    table.add_column("ID", style="cyan")
    table.add_column("Status", style="yellow")
    table.add_column("Created", style="green")
    table.add_column("Size", style="blue")

    for b in backups:
        size_mb = b.size_bytes / (1024 * 1024) if b.size_bytes else 0
        table.add_row(
            b.id,
            b.status,
            b.created_at,
            f"{size_mb:.1f} MB" if size_mb else "N/A",
        )

    console.print(table)


@fly_db_app.command()
@with_error_handling
def reset(
    cluster: Annotated[
        str | None,
        typer.Option("--cluster", "-c", help="Cluster ID or name"),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Organization filter"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Reset database to clean state.

    WARNING: This will delete all data in the application database.
    Uses fly proxy to connect to the cluster from your local machine.
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("Reset Fly Postgres Database")

    cluster_info = _select_cluster(controller, cluster, org=org)

    if not force:
        confirmed = console.confirm_action(
            action=f"Reset database in cluster: {cluster_info.name}",
            details="This will delete all application data.",
            extra_warning="This action cannot be undone!",
            force=force,
        )
        if not confirmed:
            console.info("Reset cancelled.")
            raise typer.Exit(0)

    console.info(f"Resetting cluster: {cluster_info.name} (ID: {cluster_info.id})")

    # Pass cluster ID to runtime so it can set up the fly proxy tunnel
    runtime = _get_runtime(cluster_info.id, legacy=cluster_info.is_legacy)

    success = run_reset(runtime, include_temporal=False, superuser_mode=True)
    if success:
        console.ok("Database reset completed")
    else:
        console.error("Database reset failed")
        raise typer.Exit(1)


@fly_db_app.command()
@with_error_handling
def migrate(
    cluster: Annotated[
        str | None,
        typer.Option("--cluster", "-c", help="Cluster ID or name"),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Organization filter"),
    ] = None,
    revision: Annotated[
        str,
        typer.Option("--revision", "-r", help="Target revision (default: head)"),
    ] = "head",
) -> None:
    """Run Alembic database migrations.

    Applies pending migrations to bring the database schema up to date.
    Uses fly proxy to connect to the cluster from your local machine.
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("Migrate Fly Postgres Database")

    cluster_info = _select_cluster(controller, cluster, org=org)
    console.info(f"Migrating cluster: {cluster_info.name} (ID: {cluster_info.id})")

    # Pass cluster ID to runtime so it can set up the fly proxy tunnel
    runtime = _get_runtime(cluster_info.id, legacy=cluster_info.is_legacy)

    # Run migrations (returns None, throws on error)
    run_migrate(
        runtime=runtime,
        action="upgrade",
        revision=revision,
        message=None,
        merge_revisions=[],
        purge=False,
        autogenerate=False,
        sql=False,
    )
    console.ok(f"Migrations applied successfully (target: {revision})")
