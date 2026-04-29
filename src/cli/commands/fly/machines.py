"""Fly.io machine and app management commands."""

from typing import Annotated

import typer
from rich.table import Table

from src.cli.shared.console import console, with_error_handling
from src.cli.shared.fly import check_prerequisites, get_fly_controller

from . import fly_app
from .settings import _get_app_name, _load_fly_app_settings


@fly_app.command(name="apps")
@with_error_handling
def list_apps(
    org: Annotated[
        str | None,
        typer.Option(
            "--org",
            "-o",
            help="Filter by organization",
        ),
    ] = None,
) -> None:
    """List Fly.io apps."""
    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("Fly.io Apps")

    apps = controller.apps_list(org=org)

    if not apps:
        console.info("No apps found.")
        console.info("Deploy with: uv run api-forge-cli fly up")
        return

    table = Table()
    table.add_column("Name", style="cyan")
    table.add_column("Organization", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Hostname", style="dim")

    for app in apps:
        status_color = "green" if app.status == "deployed" else "yellow"
        table.add_row(
            app.name,
            app.organization,
            f"[{status_color}]{app.status}[/{status_color}]",
            app.hostname,
        )

    console.print(table)


@fly_app.command(name="machines")
@with_error_handling
def list_machines(
    app: Annotated[
        str | None,
        typer.Option(
            "--app",
            "-a",
            help="App name (from config if not specified)",
        ),
    ] = None,
) -> None:
    """List machines for the Fly.io app."""
    controller = get_fly_controller()
    check_prerequisites(controller)

    settings = _load_fly_app_settings()
    effective_app = _get_app_name(app, settings)

    console.print_header(f"Machines: {effective_app}")

    machines = controller.machines_list(effective_app)

    if not machines:
        console.info("No machines found.")
        return

    table = Table()
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Region", style="blue")
    table.add_column("State", style="yellow")
    table.add_column("Created", style="dim")

    for machine in machines:
        state = machine.get("state", "unknown")
        state_color = "green" if state == "started" else "yellow"
        table.add_row(
            machine.get("id", ""),
            machine.get("name", ""),
            machine.get("region", ""),
            f"[{state_color}]{state}[/{state_color}]",
            machine.get("created_at", "")[:19] if machine.get("created_at") else "",
        )

    console.print(table)


@fly_app.command(name="machine-stop")
@with_error_handling
def machine_stop(
    machine_id: Annotated[
        str,
        typer.Argument(help="Machine ID to stop"),
    ],
    app: Annotated[
        str | None,
        typer.Option(
            "--app",
            "-a",
            help="App name (from config if not specified)",
        ),
    ] = None,
) -> None:
    """Stop a specific machine."""
    controller = get_fly_controller()
    check_prerequisites(controller)

    settings = _load_fly_app_settings()
    effective_app = _get_app_name(app, settings)

    console.info(f"Stopping machine {machine_id}...")

    result = controller.machine_stop(effective_app, machine_id)

    if result.success:
        console.ok(f"Machine {machine_id} stopped")
    else:
        console.error("Failed to stop machine")
        if result.stderr:
            console.info(result.stderr)
        raise typer.Exit(1)


@fly_app.command(name="machine-start")
@with_error_handling
def machine_start(
    machine_id: Annotated[
        str,
        typer.Argument(help="Machine ID to start"),
    ],
    app: Annotated[
        str | None,
        typer.Option(
            "--app",
            "-a",
            help="App name (from config if not specified)",
        ),
    ] = None,
) -> None:
    """Start a specific machine."""
    controller = get_fly_controller()
    check_prerequisites(controller)

    settings = _load_fly_app_settings()
    effective_app = _get_app_name(app, settings)

    console.info(f"Starting machine {machine_id}...")

    result = controller.machine_start(effective_app, machine_id)

    if result.success:
        console.ok(f"Machine {machine_id} started")
    else:
        console.error("Failed to start machine")
        if result.stderr:
            console.info(result.stderr)
        raise typer.Exit(1)


@fly_app.command(name="machine-destroy")
@with_error_handling
def machine_destroy(
    machine_id: Annotated[
        str,
        typer.Argument(help="Machine ID to destroy"),
    ],
    app: Annotated[
        str | None,
        typer.Option(
            "--app",
            "-a",
            help="App name (from config if not specified)",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Force destruction even if running",
        ),
    ] = False,
) -> None:
    """Destroy a specific machine."""
    controller = get_fly_controller()
    check_prerequisites(controller)

    settings = _load_fly_app_settings()
    effective_app = _get_app_name(app, settings)

    console.info(f"Destroying machine {machine_id}...")

    result = controller.machine_destroy(effective_app, machine_id, force=force)

    if result.success:
        console.ok(f"Machine {machine_id} destroyed")
    else:
        console.error("Failed to destroy machine")
        if result.stderr:
            console.info(result.stderr)
        raise typer.Exit(1)
