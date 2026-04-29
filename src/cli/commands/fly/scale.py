"""Fly.io 'scale' command."""

from typing import Annotated

import typer

from src.cli.shared.console import console, with_error_handling
from src.cli.shared.fly import check_prerequisites, get_fly_controller

from . import fly_app
from .settings import _get_app_name, _load_fly_app_settings


@fly_app.command()
@with_error_handling
def scale(
    app: Annotated[
        str | None,
        typer.Option(
            "--app",
            "-a",
            help="App name (from config if not specified)",
        ),
    ] = None,
    count: Annotated[
        int | None,
        typer.Option(
            "--count",
            "-c",
            help="Number of machines",
        ),
    ] = None,
    vm: Annotated[
        str | None,
        typer.Option(
            "--vm",
            help="VM size (e.g., shared-cpu-1x, performance-1x)",
        ),
    ] = None,
    memory: Annotated[
        int | None,
        typer.Option(
            "--memory",
            "-m",
            help="Memory in MB",
        ),
    ] = None,
    region: Annotated[
        str | None,
        typer.Option(
            "--region",
            "-r",
            help="Region to scale in (for count)",
        ),
    ] = None,
) -> None:
    """Scale the Fly.io deployment.

    Scale machine count, VM size, or memory allocation.
    At least one scaling option must be specified.

    Examples:
        uv run api-forge-cli fly scale --count 3
        uv run api-forge-cli fly scale --vm performance-1x
        uv run api-forge-cli fly scale --memory 512
        uv run api-forge-cli fly scale --count 2 --region iad
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    settings = _load_fly_app_settings()
    effective_app = _get_app_name(app, settings)

    if count is None and vm is None and memory is None:
        console.error("At least one of --count, --vm, or --memory must be specified.")
        raise typer.Exit(1)

    console.print_header(f"Scale: {effective_app}")

    success = True

    if count is not None:
        console.info(f"Scaling to {count} machines...")
        result = controller.scale_count(effective_app, count, region=region)
        if result.success:
            console.ok(f"Scaled to {count} machines")
        else:
            console.error(f"Failed to scale count: {result.stderr}")
            success = False

    if vm is not None:
        console.info(f"Setting VM size to {vm}...")
        result = controller.scale_vm(effective_app, vm)
        if result.success:
            console.ok(f"VM size set to {vm}")
        else:
            console.error(f"Failed to scale VM: {result.stderr}")
            success = False

    if memory is not None:
        console.info(f"Setting memory to {memory}MB...")
        result = controller.scale_memory(effective_app, memory)
        if result.success:
            console.ok(f"Memory set to {memory}MB")
        else:
            console.error(f"Failed to scale memory: {result.stderr}")
            success = False

    if not success:
        raise typer.Exit(1)
