"""``api-forge-cli activity`` Typer commands."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.prompt import Prompt

from src.app.runtime.context import get_config
from src.cli.shared.console import console

from .scaffold import (
    create_activity_files,
    prompt_for_input_fields,
    sanitize_activity_name,
)

activity_app = typer.Typer(help="⚡ Temporal activity scaffolding commands")


def _ensure_temporal_enabled() -> None:
    if not get_config().temporal.enabled:
        console.error("Temporal is disabled (config.temporal.enabled=false).")
        console.print(
            "  Activities only make sense within Temporal workflows; without "
            "Temporal there's nothing to call them."
        )
        console.print()
        console.print(
            "  For fire-and-forget async work without Temporal, use FastAPI "
            "BackgroundTasks instead."
        )
        raise typer.Exit(2)


@activity_app.command()
def add(
    activity_name: str = typer.Argument(
        None, help="Name of the activity to add (snake_case)"
    ),
    queue: str = typer.Option(
        "default",
        "--queue",
        "-q",
        help="Temporal task queue this activity runs on",
    ),
) -> None:
    """➕ Scaffold a new Temporal activity.

    Generates ``src/app/worker/activities/<name>.py`` and a matching unit
    test. The activity is auto-discovered by the worker registry.
    """
    _ensure_temporal_enabled()

    if not activity_name:
        activity_name = Prompt.ask("[cyan]Activity name (snake_case)")
    activity_name = sanitize_activity_name(activity_name)

    console.print(
        Panel.fit(
            f"[bold green]Scaffolding activity: {activity_name}[/bold green]",
            border_style="green",
        )
    )

    fields = prompt_for_input_fields()
    if not fields:
        console.print(
            "[yellow]⚠ No input fields supplied — generating an empty Input model.[/yellow]"
        )

    try:
        activity_path, test_path = create_activity_files(
            activity_name, fields, queue=queue
        )
    except FileExistsError as exc:
        console.error(str(exc))
        raise typer.Exit(1) from exc

    console.ok(f"Activity scaffolded: {activity_path}")
    console.ok(f"Test scaffolded:     {test_path}")
    console.print()
    console.print("[blue]Next steps:[/blue]")
    console.print("  1. Implement the activity body (replace NotImplementedError)")
    console.print(
        "  2. Call from a workflow: await self.execute_activity(name, input, ...)"
    )
