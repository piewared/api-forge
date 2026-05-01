"""Entity scaffolding utilities."""

from __future__ import annotations

import re
from pathlib import Path

from rich.prompt import Prompt

from src.cli.shared.console import console
from src.utils.paths import get_package_root

from .templates import render_template_to_file


def sanitize_entity_name(name: str) -> str:
    """Sanitize entity name to PascalCase, accepting snake_case, kebab-case,
    camelCase, and already-PascalCase as input.

    Note: split on lowercase→uppercase boundaries first so that
    ``"OrderItem"`` round-trips. Without that, ``str.capitalize()`` would
    lowercase the second word ("Orderitem").
    """
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    words = re.findall(r"[a-zA-Z0-9]+", name)
    return "".join(word.capitalize() for word in words)


def sanitize_field_name(name: str) -> str:
    """Sanitize field name to conform to Python snake_case conventions."""
    words = re.findall(r"[a-zA-Z0-9]+", name)
    return "_".join(word.lower() for word in words)


def prompt_for_fields() -> list[dict[str, str | bool]]:
    """Prompt user for entity fields."""
    fields: list[dict[str, str | bool]] = []
    console.print(
        "\n[blue]Define entity fields (press Enter without a name to finish):[/blue]"
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
                f"[cyan]Is '{field_name}' optional?", choices=["y", "n"], default="n"
            )
            == "y"
        )

        description = Prompt.ask(
            f"[cyan]Description for '{field_name}'",
            default=f"{field_name.replace('_', ' ').title()}",
        )

        fields.append(
            {
                "name": field_name,
                "type": field_type,
                "optional": optional,
                "description": description,
            }
        )

        console.print(f"[green]✓[/green] Added field: {field_name}: {field_type}")

    return fields


def create_entity_files(
    entity_name: str,
    fields: list[dict[str, str | bool]],
    package_path: Path,
    *,
    with_temporal: bool = False,
    workflow_name: str | None = None,
) -> None:
    """Create all entity files using Jinja2 templates.

    The router is colocated with the entity (``router.py``) so it's picked up
    by the auto-discovery loader at app startup — no edit to ``app.py`` needed.

    Args:
        entity_name: PascalCase name of the entity.
        fields: list of ``{"name", "type", "optional", "description"}`` dicts.
        package_path: target directory for the generated package.
        with_temporal: when True, the service ctor accepts and stores a
            ``TemporalClientService`` and the router's
            ``get_<entity>_service`` factory injects it via FastAPI deps.
            Auto-set when ``workflow_name`` is provided.
        workflow_name: when set (e.g., ``"OrderDispatch"``), an async
            ``dispatch()`` method is rendered into the service that starts
            the corresponding workflow. Implies ``with_temporal=True``.
    """
    if workflow_name and not with_temporal:
        with_temporal = True

    context = {
        "entity_name": entity_name,
        "fields": fields,
        "with_temporal": with_temporal,
        "workflow_name": workflow_name,
    }

    render_template_to_file("entity.py.j2", package_path / "entity.py", context)
    render_template_to_file("table.py.j2", package_path / "table.py", context)
    render_template_to_file("repository.py.j2", package_path / "repository.py", context)
    render_template_to_file("schemas.py.j2", package_path / "schemas.py", context)
    render_template_to_file("service.py.j2", package_path / "service.py", context)
    render_template_to_file("router.py.j2", package_path / "router.py", context)
    render_template_to_file("__init__.py.j2", package_path / "__init__.py", context)


def get_entity_package_path(entity_name: str) -> Path:
    """Return the on-disk path for a given entity package."""
    return get_package_root() / "app" / "entities" / "service" / entity_name.lower()
