"""``api-forge-cli workflow`` Typer commands."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.prompt import Prompt

from src.app.runtime.context import get_config
from src.cli.shared.console import console

from .scaffold import (
    create_workflow_files,
    prompt_for_input_fields,
    sanitize_workflow_name,
)

workflow_app = typer.Typer(help="🔄 Temporal workflow scaffolding commands")


def _ensure_temporal_enabled() -> None:
    """Refuse to scaffold workflows when Temporal is off.

    A workflow without Temporal isn't a workflow — it's a fire-and-forget
    task. For that case use FastAPI's BackgroundTasks; we don't substitute
    a leaky in-memory executor that silently drops durability guarantees.
    """
    if not get_config().temporal.enabled:
        console.error("Temporal is disabled (config.temporal.enabled=false).")
        console.print(
            "  Workflow scaffolding only makes sense when Temporal is the "
            "execution backend."
        )
        console.print()
        console.print("  Either:")
        console.print("    1. Enable Temporal in config.yaml and rerun, or")
        console.print(
            "    2. Use FastAPI BackgroundTasks for fire-and-forget async work."
        )
        raise typer.Exit(2)


@workflow_app.command()
def add(
    workflow_name: str = typer.Argument(
        None, help="Name of the workflow to add (PascalCase)"
    ),
    queue: str = typer.Option(
        "default",
        "--queue",
        "-q",
        help="Temporal task queue this workflow runs on",
    ),
) -> None:
    """➕ Scaffold a new Temporal workflow.

    Generates ``src/app/worker/workflows/<name>.py`` (typed Input/Result +
    BaseWorkflow subclass) and a matching unit test. The workflow is auto-
    discovered by ``src/app/worker/registry.py`` at worker startup.
    """
    _ensure_temporal_enabled()

    if not workflow_name:
        workflow_name = Prompt.ask("[cyan]Workflow name (PascalCase)")
    workflow_name = sanitize_workflow_name(workflow_name)

    console.print(
        Panel.fit(
            f"[bold green]Scaffolding workflow: {workflow_name}[/bold green]",
            border_style="green",
        )
    )

    fields = prompt_for_input_fields()
    if not fields:
        console.print(
            "[yellow]⚠ No input fields supplied — generating an empty Input model.[/yellow]"
        )

    try:
        workflow_path, test_path = create_workflow_files(
            workflow_name, fields, queue=queue
        )
    except FileExistsError as exc:
        console.error(str(exc))
        raise typer.Exit(1) from exc

    console.ok(f"Workflow scaffolded: {workflow_path}")
    console.ok(f"Test scaffolded:     {test_path}")
    console.print()
    console.print("[blue]Next steps:[/blue]")
    console.print(
        f"  1. Implement the run() method in {workflow_path.relative_to(workflow_path.parents[3])}"
    )
    console.print("  2. Trigger from a service via TemporalClientService.get_client()")
    console.print("     + WorkflowName.start_workflow(client, input=..., id=...)")
    console.print("  3. See docs/fastapi-temporal-workflows.md for the full pattern.")
