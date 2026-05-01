"""Fly.io 'logs' command."""

from typing import Annotated

import typer

from src.cli.commands.fly._prereq import check_prerequisites, get_fly_controller
from src.cli.shared.console import console, with_error_handling

from . import fly_app
from .settings import _get_app_name, _load_fly_app_settings


@fly_app.command()
@with_error_handling
def logs(
    app: Annotated[
        str | None,
        typer.Option(
            "--app",
            "-a",
            help="App name (from config if not specified)",
        ),
    ] = None,
    region: Annotated[
        str | None,
        typer.Option(
            "--region",
            "-r",
            help="Filter by region",
        ),
    ] = None,
    instance: Annotated[
        str | None,
        typer.Option(
            "--instance",
            "-i",
            help="Filter by instance ID",
        ),
    ] = None,
) -> None:
    """View logs from Fly.io deployment.

    Shows recent logs. For streaming logs, use flyctl directly.

    Examples:
        uv run api-forge-cli fly logs
        uv run api-forge-cli fly logs --region iad

        # For streaming:
        fly logs --app <app-name>
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    settings = _load_fly_app_settings()
    effective_app = _get_app_name(app, settings)

    console.info(f"Fetching logs for {effective_app}...")

    result = controller.logs(effective_app, region=region, instance=instance)

    if result.success:
        console.print()
        console.print(result.stdout)
    else:
        console.error("Failed to fetch logs")
        if result.stderr:
            console.info(result.stderr)
        raise typer.Exit(1)

    console.print()
    console.info(f"For streaming logs: fly logs --app {effective_app}")
