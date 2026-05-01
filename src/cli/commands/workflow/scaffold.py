"""Workflow scaffolding helpers — generation logic, no Typer wiring."""

from __future__ import annotations

import re
from pathlib import Path

from rich.prompt import Prompt

from src.cli.commands.entity.templates import render_template_to_file
from src.cli.shared.console import console
from src.utils.paths import get_package_root, get_project_root


def sanitize_workflow_name(name: str) -> str:
    """Normalise a name to PascalCase, accepting snake_case, kebab-case,
    camelCase, and already-PascalCase as input.

    Note: ``str.capitalize()`` lowercases everything after the first letter,
    so naive ``"OrderDispatch".capitalize()`` produces ``"Orderdispatch"`` —
    a real bug if a user passes an already-cased name. We split on
    lowercase→uppercase transitions first so PascalCase round-trips.
    """
    # Insert a space at every lowercase/digit → uppercase boundary so
    # camelCase / PascalCase get split into their constituent words.
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    words = re.findall(r"[a-zA-Z0-9]+", name)
    return "".join(word.capitalize() for word in words)


def sanitize_field_name(name: str) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", name)
    return "_".join(word.lower() for word in words)


def prompt_for_input_fields() -> list[dict[str, str | bool]]:
    """Prompt the user for the workflow's input fields. Same shape as the
    entity prompt so the experience stays consistent.
    """
    fields: list[dict[str, str | bool]] = []
    console.print(
        "\n[blue]Define workflow input fields (press Enter without a name to finish):[/blue]"
    )
    while True:
        field_name = Prompt.ask("[cyan]Field name", default="")
        if not field_name.strip():
            break
        field_name = sanitize_field_name(field_name)
        field_type = Prompt.ask(
            f"[cyan]Type for '{field_name}'",
            choices=["str", "int", "float", "bool", "datetime"],
            default="str",
        )
        optional = (
            Prompt.ask(
                f"[cyan]Is '{field_name}' optional?",
                choices=["y", "n"],
                default="n",
            )
            == "y"
        )
        fields.append(
            {
                "name": field_name,
                "type": field_type,
                "optional": optional,
            }
        )
        console.print(f"[green]✓[/green] Added field: {field_name}: {field_type}")
    return fields


def get_workflow_module_path(workflow_name: str) -> Path:
    """Where the generated workflow lives on disk."""
    return (
        get_package_root()
        / "app"
        / "worker"
        / "workflows"
        / f"{workflow_name.lower()}.py"
    )


def get_workflow_test_path(workflow_name: str) -> Path:
    """Mirror under tests/unit/app/worker/."""
    return (
        get_project_root()
        / "tests"
        / "unit"
        / "app"
        / "worker"
        / f"test_{workflow_name.lower()}_workflow.py"
    )


def create_workflow_files(
    workflow_name: str,
    fields: list[dict[str, str | bool]],
    *,
    queue: str = "default",
) -> tuple[Path, Path]:
    """Render the workflow + its test. Returns the two file paths."""
    context = {
        "workflow_name": workflow_name,
        "fields": fields,
        "queue": queue,
    }

    workflow_path = get_workflow_module_path(workflow_name)
    test_path = get_workflow_test_path(workflow_name)

    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.parent.mkdir(parents=True, exist_ok=True)

    render_template_to_file("workflow.py.j2", workflow_path, context)
    render_template_to_file("workflow_test.py.j2", test_path, context)

    return workflow_path, test_path
