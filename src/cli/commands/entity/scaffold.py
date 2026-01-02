"""Entity scaffolding utilities."""

from __future__ import annotations

import re
from pathlib import Path

from rich.prompt import Prompt

from src.cli.shared.console import console
from src.utils.paths import get_project_root

from .templates import render_template_to_file


def sanitize_entity_name(name: str) -> str:
    """Sanitize entity name to conform to Python naming conventions."""
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
    entity_name: str, fields: list[dict[str, str | bool]], package_path: Path
) -> None:
    """Create all entity files using Jinja2 templates."""
    context = {"entity_name": entity_name, "fields": fields}

    render_template_to_file("entity.py.j2", package_path / "entity.py", context)
    render_template_to_file("table.py.j2", package_path / "table.py", context)
    render_template_to_file("repository.py.j2", package_path / "repository.py", context)
    render_template_to_file("__init__.py.j2", package_path / "__init__.py", context)


def create_crud_router(entity_name: str, fields: list[dict[str, str | bool]]) -> None:
    """Create a CRUD router for the entity using templates."""
    router_dir = (
        get_project_root() / "src" / "app" / "api" / "http" / "routers" / "service"
    )
    router_dir.mkdir(parents=True, exist_ok=True)

    router_file = router_dir / f"{entity_name.lower()}.py"
    context = {"entity_name": entity_name, "fields": fields}
    render_template_to_file("router.py.j2", router_file, context)

    routers_init = router_dir / "__init__.py"
    if not routers_init.exists():
        routers_init.write_text('"""Service routers package."""\n')


def register_router_with_app(entity_name: str) -> None:
    """Add import and registration for the new router in app.py."""
    app_file = get_project_root() / "src" / "app" / "api" / "http" / "app.py"

    content = app_file.read_text()

    import_line = (
        "from src.app.api.http.routers.service."
        f"{entity_name.lower()} import router as {entity_name.lower()}_router"
    )

    lines = content.split("\n")
    import_insert_idx = -1

    for i, line in enumerate(lines):
        if "from src.app.api.http.routers" in line and "import router" in line:
            import_insert_idx = i + 1

    if import_insert_idx > 0:
        lines.insert(import_insert_idx, import_line)
    else:
        for i, line in enumerate(lines):
            if line.startswith("from src.app") and "import" in line:
                import_insert_idx = i + 1
        if import_insert_idx > 0:
            lines.insert(import_insert_idx, import_line)

    registration_line = (
        f"app.include_router({entity_name.lower()}_router, "
        f'prefix="/api/v1/{entity_name.lower()}s", tags=["{entity_name.lower()}s"])'
    )

    for i, line in enumerate(lines):
        if "app.include_router" in line and "your_router" in line:
            lines.insert(i, registration_line)
            break
    else:
        register_insert_idx = -1
        for i, line in enumerate(lines):
            if "app.include_router" in line and "your_router" not in line:
                register_insert_idx = i + 1

        if register_insert_idx > 0:
            lines.insert(register_insert_idx, registration_line)

    app_file.write_text("\n".join(lines))


def unregister_router_from_app(entity_name: str) -> None:
    """Remove router import and registration from app.py."""
    project_root = get_project_root()
    app_file = project_root / "src" / "app" / "api" / "http" / "app.py"

    if not app_file.exists():
        console.print(
            "[yellow]⚠️  app.py not found, skipping router unregistration[/yellow]"
        )
        return

    content = app_file.read_text()
    lines = content.split("\n")
    new_lines = []

    import_pattern = (
        "from src.app.api.http.routers.service."
        f"{entity_name.lower()} import router as {entity_name.lower()}_router"
    )
    include_pattern = (
        f"app.include_router({entity_name.lower()}_router, "
        f'prefix="/api/v1/{entity_name.lower()}s", tags=["{entity_name.lower()}s"])'
    )

    import_found = False
    include_found = False

    for line in lines:
        if import_pattern in line:
            console.print(f"  ✅ Removed import: {line.strip()}")
            import_found = True
            continue

        if include_pattern in line:
            console.print(f"  ✅ Removed registration: {line.strip()}")
            include_found = True
            continue

        new_lines.append(line)

    if not import_found:
        console.print("[yellow]⚠️  Import pattern not found in app.py[/yellow]")
    if not include_found:
        console.print("[yellow]⚠️  Include pattern not found in app.py[/yellow]")

    if import_found or include_found:
        app_file.write_text("\n".join(new_lines))
    else:
        console.print("[yellow]⚠️  No changes made to app.py[/yellow]")
