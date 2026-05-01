"""Fly Postgres management commands (list, status, attach, connect, destroy)."""

from typing import Annotated

import typer

from src.cli.commands.fly._prereq import (
    check_authenticated,
    check_flyctl_installed,
    get_fly_controller,
)
from src.cli.shared.console import console, with_error_handling

from . import fly_db_app
from .select import _select_cluster


@fly_db_app.command()
@with_error_handling
def list_dbs(
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Filter by organization"),
    ] = None,
) -> None:
    """List Fly Postgres databases.

    Shows both Fly Managed Postgres (MPG) and legacy Fly Postgres clusters.
    """
    from rich.table import Table

    controller = get_fly_controller()
    check_flyctl_installed(controller)
    check_authenticated(controller)

    console.print_header("Fly Postgres Databases")

    # List MPG clusters
    mpg_clusters = controller.mpg_list(org=org)

    if mpg_clusters:
        table = Table(title="Fly Managed Postgres")
        table.add_column("Name", style="cyan")
        table.add_column("Region", style="green")
        table.add_column("Plan", style="blue")
        table.add_column("Status", style="yellow")
        table.add_column("ID", style="dim")

        for cluster in mpg_clusters:
            status_color = "green" if cluster.status == "running" else "yellow"
            table.add_row(
                cluster.name,
                cluster.region,
                cluster.plan,
                f"[{status_color}]{cluster.status}[/{status_color}]",
                cluster.id,
            )

        console.print(table)
    else:
        console.info("No Fly Managed Postgres clusters found.")

    # List legacy Postgres
    legacy_clusters = controller.postgres_list()

    if legacy_clusters:
        console.print()
        table = Table(title="Fly Postgres (Legacy)")
        table.add_column("Name", style="cyan")
        table.add_column("Status", style="yellow")
        table.add_column("Organization", style="green")

        for pg_cluster in legacy_clusters:
            table.add_row(
                pg_cluster.name,
                pg_cluster.status,
                pg_cluster.organization,
            )

        console.print(table)

    if not mpg_clusters and not legacy_clusters:
        console.info(
            "Create a database with: api-forge-cli fly db create --name my-db --region iad"
        )


@fly_db_app.command()
@with_error_handling
def attach(
    cluster: Annotated[
        str | None,
        typer.Option("--cluster", "-c", help="Cluster ID or name"),
    ] = None,
    app: Annotated[
        str | None,
        typer.Option("--app", "-a", help="Fly app name to attach"),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Organization filter"),
    ] = None,
    database_name: Annotated[
        str | None,
        typer.Option("--database", "-d", help="Database name (default: app database)"),
    ] = None,
    variable: Annotated[
        str,
        typer.Option(
            "--variable", "-v", help="Environment variable name for connection string"
        ),
    ] = "DATABASE_URL",
) -> None:
    """Attach a Fly app to the Postgres cluster.

    Sets the DATABASE_URL secret on the app with the connection string.
    """
    controller = get_fly_controller()
    check_flyctl_installed(controller)
    check_authenticated(controller)

    console.print_header("Attach App to Fly Postgres")

    cluster_info = _select_cluster(controller, cluster, org=org)

    if app is None:
        console.error("--app is required to attach a cluster")
        raise typer.Exit(1)

    console.info(f"Attaching app '{app}' to cluster '{cluster_info.name}'")

    result = controller.mpg_attach(
        cluster_info.id,
        app,
        database_name=database_name,
        variable_name=variable,
    )

    if result.success:
        console.ok(f"App '{app}' attached to cluster '{cluster_info.name}'")
        console.info(f"Secret '{variable}' set on app")
    else:
        console.error("Failed to attach app to cluster")
        if result.stderr:
            console.print(f"[dim]{result.stderr}[/dim]")
        raise typer.Exit(1)


@fly_db_app.command()
@with_error_handling
def connect(
    cluster: Annotated[
        str | None,
        typer.Option("--cluster", "-c", help="Cluster ID or name"),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Organization filter"),
    ] = None,
) -> None:
    """Open interactive psql session to the database.

    Starts a psql connection to the Fly Postgres cluster.
    """
    controller = get_fly_controller()
    check_flyctl_installed(controller)
    check_authenticated(controller)

    cluster_info = _select_cluster(controller, cluster, org=org)

    console.info(f"Connecting to cluster: {cluster_info.name}")
    console.info("Starting psql session... (Ctrl+D to exit)")

    # This runs interactively
    controller.mpg_connect(cluster_info.id)


@fly_db_app.command()
@with_error_handling
def destroy(
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
    """Destroy a Fly Postgres cluster.

    WARNING: This will permanently delete the cluster and all data.
    """
    controller = get_fly_controller()
    check_flyctl_installed(controller)
    check_authenticated(controller)

    console.print_header("Destroy Fly Postgres Cluster")

    cluster_info = _select_cluster(controller, cluster, org=org)

    if not force:
        confirmed = console.confirm_action(
            action=f"DESTROY cluster: {cluster_info.name}",
            details=f"Region: {cluster_info.region}, Plan: {cluster_info.plan}",
            extra_warning="This will PERMANENTLY DELETE ALL DATA. This cannot be undone!",
            force=force,
        )
        if not confirmed:
            console.info("Destroy cancelled.")
            raise typer.Exit(0)

    console.warn(f"Destroying cluster: {cluster_info.name}")

    result = controller.mpg_destroy(cluster_info.id, confirm=True)

    if result.success:
        console.ok(f"Cluster '{cluster_info.name}' destroyed")
    else:
        console.error("Failed to destroy cluster")
        if result.stderr:
            console.print(f"[dim]{result.stderr}[/dim]")
        raise typer.Exit(1)
