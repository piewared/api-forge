"""Activity scaffolding helpers — generation logic, no Typer wiring."""

from __future__ import annotations

import re
from pathlib import Path

from rich.prompt import Prompt

from src.cli.commands.entity.templates import render_template_to_file
from src.cli.shared.console import console
from src.utils.paths import get_package_root, get_project_root


def sanitize_activity_name(name: str) -> str:
    """Activities are functions, so we want snake_case.

    Accept either ``send_email`` or ``SendEmail`` and produce both the
    snake_case function name and the PascalCase prefix for the
    Input/Result models.
    """
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", name)
    return "_".join(w.lower() for w in words) if words else name.lower()


def to_pascal(snake: str) -> str:
    return "".join(w.capitalize() for w in snake.split("_"))


def sanitize_field_name(name: str) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", name)
    return "_".join(word.lower() for word in words)


def prompt_for_input_fields() -> list[dict[str, str | bool]]:
    fields: list[dict[str, str | bool]] = []
    console.print(
        "\n[blue]Define activity input fields (press Enter without a name to finish):[/blue]"
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
        fields.append({"name": field_name, "type": field_type, "optional": optional})
        console.print(f"[green]✓[/green] Added field: {field_name}: {field_type}")
    return fields


def get_activity_module_path(activity_name: str) -> Path:
    return get_package_root() / "app" / "worker" / "activities" / f"{activity_name}.py"


def get_activity_test_path(activity_name: str) -> Path:
    return (
        get_project_root()
        / "tests"
        / "unit"
        / "app"
        / "worker"
        / f"test_{activity_name}_activity.py"
    )


def create_activity_files(
    activity_name: str,
    fields: list[dict[str, str | bool]],
    *,
    queue: str = "default",
) -> tuple[Path, Path]:
    """Render the activity + its test. Returns the two file paths."""
    context = {
        "activity_name": activity_name,
        "activity_class": to_pascal(activity_name),
        "fields": fields,
        "queue": queue,
    }

    activity_path = get_activity_module_path(activity_name)
    test_path = get_activity_test_path(activity_name)

    activity_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.parent.mkdir(parents=True, exist_ok=True)

    render_template_to_file("activity.py.j2", activity_path, context)
    render_template_to_file("activity_test.py.j2", test_path, context)

    return activity_path, test_path
