"""Fly.io 'status' command — show deployment status."""

from typing import Annotated

import typer
from rich.table import Table

from src.cli.commands.fly._prereq import check_prerequisites, get_fly_controller
from src.cli.shared.console import console, with_error_handling

from . import fly_app
from .settings import _get_app_name, _load_fly_app_settings


@fly_app.command()
@with_error_handling
def status(
    app: Annotated[
        str | None,
        typer.Option(
            "--app",
            "-a",
            help="App name (from config if not specified)",
        ),
    ] = None,
    show_all: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Show status of all Fly.io services (app, database, etc)",
        ),
    ] = True,
) -> None:
    """Show Fly.io deployment status.

    Displays detailed status including machines, regions, and health.
    By default shows both app and database status.
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    settings = _load_fly_app_settings()
    effective_app = _get_app_name(app, settings)

    console.print_header("Fly.io Deployment Status")

    # -------------------------------------------------------------------------
    # App Status
    # -------------------------------------------------------------------------
    console.print_subheader(f"App: {effective_app}")

    app_info = controller.app_info(effective_app)
    if not app_info:
        console.error(f"App '{effective_app}' not found.")
        console.info("Deploy with: uv run api-forge-cli fly up")
    else:
        # Basic info table
        info_table = Table(show_header=False, box=None)
        info_table.add_column("Key", style="dim")
        info_table.add_column("Value")

        info_table.add_row("Name", app_info.name)
        info_table.add_row("Organization", app_info.organization)
        status_color = "green" if app_info.status == "deployed" else "yellow"
        info_table.add_row(
            "Status", f"[{status_color}]{app_info.status}[/{status_color}]"
        )
        info_table.add_row("Hostname", app_info.hostname or f"{effective_app}.fly.dev")
        info_table.add_row("URL", f"https://{effective_app}.fly.dev")

        console.print(info_table)

        # Show machines if available
        machines = controller.machines_list(effective_app)
        if machines:
            console.print()
            console.info(f"Machines ({len(machines)} total):")

            machine_table = Table()
            machine_table.add_column("Name", style="cyan")
            machine_table.add_column("Process", style="blue")
            machine_table.add_column("Region", style="green")
            machine_table.add_column("State", style="yellow")
            machine_table.add_column("CPU/Mem", style="dim")
            machine_table.add_column("ID", style="dim")

            for machine in machines:
                state = machine.get("state", "unknown")
                state_color = "green" if state == "started" else "yellow"
                if state == "stopped":
                    state_color = "red"

                # Get config details
                config = machine.get("config", {})
                guest = config.get("guest", {})
                cpu_kind = guest.get("cpu_kind", "shared")
                cpus = guest.get("cpus", 1)
                memory_mb = guest.get("memory_mb", 256)

                # Get process group from env or metadata
                env = config.get("env", {})
                metadata = config.get("metadata", {})
                process_group = (
                    env.get("FLY_PROCESS_GROUP")
                    or metadata.get("fly_process_group")
                    or "app"
                )

                # Format CPU/Memory
                cpu_mem = f"{cpus}x {cpu_kind[:3]}, {memory_mb}MB"

                machine_table.add_row(
                    machine.get("name", ""),
                    process_group,
                    machine.get("region", ""),
                    f"[{state_color}]{state}[/{state_color}]",
                    cpu_mem,
                    machine.get("id", "")[:12],
                )

            console.print(machine_table)

    if not show_all:
        return

    # -------------------------------------------------------------------------
    # Database Status
    # -------------------------------------------------------------------------
    console.print()
    console.print_subheader("PostgreSQL Database")

    # Check managed (MPG) and legacy (unmanaged) postgres clusters
    db_clusters = controller.mpg_list()
    legacy_clusters = controller.postgres_list()

    if not db_clusters and not legacy_clusters:
        console.info("No Fly Postgres databases found.")
        console.info("Create one with: uv run api-forge-cli fly db create")
    else:
        db_table = Table()
        db_table.add_column("Name", style="cyan")
        db_table.add_column("Type", style="blue")
        db_table.add_column("Region", style="green")
        db_table.add_column("Status", style="yellow")
        db_table.add_column("Plan / Org", style="dim")
        db_table.add_column("Created", style="blue")

        for cluster in db_clusters:
            status_color = "green" if cluster.status == "ready" else "yellow"
            db_table.add_row(
                cluster.name,
                "managed",
                cluster.region,
                f"[{status_color}]{cluster.status}[/{status_color}]",
                cluster.plan,
                cluster.created_at or "—",
            )

        for db_app in legacy_clusters:
            status_color = "green" if db_app.status == "deployed" else "yellow"
            db_table.add_row(
                db_app.name,
                "[dim]legacy[/dim]",
                "—",
                f"[{status_color}]{db_app.status}[/{status_color}]",
                db_app.organization,
                "—",
            )

        console.print(db_table)

        console.print()
        console.info("Database connection:")
        first = db_clusters[0].name if db_clusters else legacy_clusters[0].name
        console.info(f"  Connect: uv run api-forge-cli fly db connect --app {first}")

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    console.print()
    console.print_subheader("Useful commands")
    console.info("  Logs:   uv run api-forge-cli fly logs")
    console.info("  Scale:  uv run api-forge-cli fly scale --count 2")
    console.info("  Deploy: uv run api-forge-cli fly up")
