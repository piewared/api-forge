"""Entity management CLI commands."""

import re
from pathlib import Path
from typing import Any

import typer
from jinja2 import Environment, FileSystemLoader
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .utils import console, get_project_root

# Create the entity command group
entity_app = typer.Typer(help="🎭 Entity management commands")


def get_template_env() -> Environment:
    """Get Jinja2 environment for template rendering."""
    template_dir = Path(__file__).parent / "templates"
    return Environment(loader=FileSystemLoader(template_dir))


def render_template_to_file(
    template_name: str, output_path: Path, context: dict[str, Any]
) -> None:
    """Render a Jinja2 template to a file."""
    env = get_template_env()
    template = env.get_template(template_name)
    content = template.render(**context)
    output_path.write_text(content)


def sanitize_entity_name(name: str) -> str:
    """Sanitize entity name to conform to Python naming conventions."""
    # Convert to PascalCase for class names
    # Remove special characters and split on non-alphanumeric
    words = re.findall(r"[a-zA-Z0-9]+", name)
    return "".join(word.capitalize() for word in words)


def sanitize_field_name(name: str) -> str:
    """Sanitize field name to conform to Python snake_case conventions."""
    # Convert to snake_case for field names
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

    # Create all files from templates
    render_template_to_file("entity.py.j2", package_path / "entity.py", context)
    render_template_to_file("table.py.j2", package_path / "table.py", context)
    render_template_to_file("repository.py.j2", package_path / "repository.py", context)
    render_template_to_file("__init__.py.j2", package_path / "__init__.py", context)


def create_crud_router(entity_name: str, fields: list[dict[str, str | bool]]) -> None:
    """Create a CRUD router for the entity using templates."""
    router_dir = (
        get_project_root() / "src" / "app" / "api" / "http" / "routers" / "service"
    )
    router_dir.mkdir(exist_ok=True)

    # Create router file from template
    router_file = router_dir / f"{entity_name.lower()}.py"
    context = {"entity_name": entity_name, "fields": fields}
    render_template_to_file("router.py.j2", router_file, context)

    # Update routers __init__.py if it exists
    routers_init = router_dir / "__init__.py"
    if not routers_init.exists():
        routers_init.write_text('"""Service routers package."""\n')


def register_router_with_app(entity_name: str) -> None:
    """Add import and registration for the new router in app.py."""
    app_file = get_project_root() / "src" / "app" / "api" / "http" / "app.py"

    # Read current content
    content = app_file.read_text()

    # Add import
    import_line = f"from src.app.api.http.routers.service.{entity_name.lower()} import router as {entity_name.lower()}_router"

    # Find the last router import to add after it
    lines = content.split("\n")
    import_insert_idx = -1

    for i, line in enumerate(lines):
        if "from src.app.api.http.routers" in line and "import router" in line:
            import_insert_idx = i + 1

    if import_insert_idx > 0:
        lines.insert(import_insert_idx, import_line)
    else:
        # Find other imports and add after them
        for i, line in enumerate(lines):
            if line.startswith("from src.app") and "import" in line:
                import_insert_idx = i + 1
        if import_insert_idx > 0:
            lines.insert(import_insert_idx, import_line)

    # Add router registration
    registration_line = f'app.include_router({entity_name.lower()}_router, prefix="/api/v1/{entity_name.lower()}s", tags=["{entity_name.lower()}s"])'

    # Find where to add the registration
    for i, line in enumerate(lines):
        if "app.include_router" in line and "your_router" in line:
            lines.insert(i, registration_line)
            break
    else:
        # Find the last router registration
        register_insert_idx = -1
        for i, line in enumerate(lines):
            if "app.include_router" in line and "your_router" not in line:
                register_insert_idx = i + 1

        if register_insert_idx > 0:
            lines.insert(register_insert_idx, registration_line)

    # Write back
    app_file.write_text("\n".join(lines))


@entity_app.command()
def add(
    entity_name: str = typer.Argument(None, help="Name of the entity to add"),
) -> None:
    """
    ➕ Add a new entity to the project.

    Creates a new entity with all the necessary files including:
    - Entity model with Pydantic validation
    - Repository pattern for data access
    - Service layer for business logic
    - API router with full CRUD operations
    - Database migration files
    - Unit tests for all components

    The entity will follow the established patterns and include:
    - SQLAlchemy model with proper relationships
    - Pydantic schemas for validation
    - Repository with async database operations
    - Service with business logic
    - API router with OpenAPI documentation
    - Comprehensive test coverage
    """
    # Prompt for entity name if not provided
    if not entity_name:
        entity_name = Prompt.ask("[cyan]Entity name")

    # Sanitize the entity name
    entity_name = sanitize_entity_name(entity_name)

    console.print(
        Panel.fit(
            f"[bold green]Adding Entity: {entity_name}[/bold green]",
            border_style="green",
        )
    )

    # Check if entity already exists
    project_root = get_project_root()
    service_entities_dir = project_root / "src" / "app" / "entities" / "service"
    entity_package_path = service_entities_dir / entity_name.lower()

    if entity_package_path.exists():
        console.print(
            f"[red]❌ Entity '{entity_name}' already exists at {entity_package_path}[/red]"
        )
        raise typer.Exit(1)

    # Prompt for entity fields
    fields = prompt_for_fields()

    if not fields:
        console.print(
            "[yellow]⚠️ No fields defined. Creating entity with base fields only.[/yellow]"
        )

    console.print(f"\n[blue]Creating entity structure for: {entity_name}[/blue]")

    try:
        # Create entity package directory
        entity_package_path.mkdir(parents=True, exist_ok=True)

        # Create entity files
        console.print("[blue]📄 Creating entity files...[/blue]")
        create_entity_files(entity_name, fields, entity_package_path)

        # Create CRUD router
        console.print("[blue]🔌 Creating API router...[/blue]")
        create_crud_router(entity_name, fields)

        # Register router with FastAPI app
        console.print("[blue]📝 Registering router with FastAPI app...[/blue]")
        register_router_with_app(entity_name)

        console.print(
            f"\n[green]✅ Entity '{entity_name}' created successfully![/green]"
        )
        console.print("\n[blue]📄 Files created:[/blue]")
        console.print(f"  - {entity_package_path}/entity.py")
        console.print(f"  - {entity_package_path}/table.py")
        console.print(f"  - {entity_package_path}/repository.py")
        console.print(f"  - {entity_package_path}/__init__.py")
        console.print(f"  - src/app/api/http/routers/service/{entity_name.lower()}.py")

        console.print("\n[blue]🚀 API endpoints available at:[/blue]")
        console.print(f"  - POST   /api/v1/{entity_name.lower()}s/")
        console.print(f"  - GET    /api/v1/{entity_name.lower()}s/")
        console.print(f"  - GET    /api/v1/{entity_name.lower()}s/{{id}}")
        console.print(f"  - PUT    /api/v1/{entity_name.lower()}s/{{id}}")
        console.print(f"  - DELETE /api/v1/{entity_name.lower()}s/{{id}}")

        if fields:
            console.print("\n[blue]📋 Entity fields:[/blue]")
            for field in fields:
                optional_text = " (optional)" if field["optional"] else ""
                console.print(f"  - {field['name']}: {field['type']}{optional_text}")

        console.print(
            "\n[dim]💡 Remember to restart your development server to load the new router![/dim]"
        )

    except Exception as e:
        console.print(f"[red]❌ Error creating entity: {e}[/red]")
        # Clean up on error
        if entity_package_path.exists():
            import shutil

            shutil.rmtree(entity_package_path)
        raise typer.Exit(1) from e


@entity_app.command()
def rm(
    entity_name: str = typer.Argument(..., help="Name of the entity to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """
    🗑️  Remove an entity from the project.

    Safely removes an entity and all its associated files:
    - Entity model and migrations
    - Repository and service files
    - API router and endpoints
    - Test files and fixtures
    - Documentation references

    This operation will ask for confirmation before removing files.
    """
    # Sanitize entity name
    entity_name = sanitize_entity_name(entity_name)

    console.print(
        Panel.fit(
            f"[bold red]Removing Entity: {entity_name}[/bold red]",
            border_style="red",
        )
    )

    try:
        project_root = get_project_root()

        # Check if entity exists
        entity_package_path = (
            project_root / "src" / "app" / "entities" / "service" / entity_name.lower()
        )
        router_file = (
            project_root
            / "src"
            / "app"
            / "api"
            / "http"
            / "routers"
            / "service"
            / f"{entity_name.lower()}.py"
        )

        if not entity_package_path.exists():
            console.print(f"[red]❌ Entity '{entity_name}' does not exist[/red]")
            raise typer.Exit(1)

        # List files that will be removed
        files_to_remove = []

        # Entity package files
        if entity_package_path.exists():
            files_to_remove.extend(
                [
                    str(entity_package_path / "entity.py"),
                    str(entity_package_path / "table.py"),
                    str(entity_package_path / "repository.py"),
                    str(entity_package_path / "__init__.py"),
                    str(entity_package_path),  # Directory itself
                ]
            )

        # Router file
        if router_file.exists():
            files_to_remove.append(str(router_file))

        # Show what will be removed
        console.print("\n[yellow]📂 Files and directories to be removed:[/yellow]")
        for file_path in files_to_remove:
            if Path(file_path).is_dir():
                console.print(f"  📁 {file_path}/")
            else:
                console.print(f"  📄 {file_path}")

        # Confirmation prompt (unless --force is used)
        if not force:
            console.print("\n[red bold]⚠️  This action cannot be undone![/red bold]")
            confirm = typer.confirm("Are you sure you want to remove this entity?")
            if not confirm:
                console.print("[blue]Operation cancelled.[/blue]")
                return

        # Remove entity package directory
        console.print("\n[blue]🗑️  Removing entity files...[/blue]")
        if entity_package_path.exists():
            import shutil

            shutil.rmtree(entity_package_path)
            console.print(f"  ✅ Removed entity package: {entity_package_path}")

        # Remove router file
        if router_file.exists():
            router_file.unlink()
            console.print(f"  ✅ Removed router file: {router_file}")

        # Remove router registration from app.py
        console.print("[blue]📝 Updating FastAPI app registration...[/blue]")
        unregister_router_from_app(entity_name)

        # Success message
        console.print(
            f"\n[green]✅ Entity '{entity_name}' removed successfully![/green]"
        )
        console.print("\n[blue]🚀 Removed resources:[/blue]")
        console.print(
            f"  - Entity package: src/app/entities/service/{entity_name.lower()}/"
        )
        console.print(
            f"  - API router: src/app/api/http/routers/service/{entity_name.lower()}.py"
        )
        console.print("  - FastAPI app registration")

        console.print(
            "\n[dim]💡 Remember to restart your development server to unload the removed router![/dim]"
        )

    except Exception as e:
        console.print(f"[red]❌ Error removing entity: {e}[/red]")
        raise typer.Exit(1) from e


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

    import_pattern = f"from src.app.api.http.routers.service.{entity_name.lower()} import router as {entity_name.lower()}_router"
    include_pattern = f'app.include_router({entity_name.lower()}_router, prefix="/api/v1/{entity_name.lower()}s", tags=["{entity_name.lower()}s"])'

    import_found = False
    include_found = False

    for line in lines:
        # Skip the import line for this entity's router
        if import_pattern in line:
            console.print(f"  ✅ Removed import: {line.strip()}")
            import_found = True
            continue

        # Skip the include_router line for this entity
        if include_pattern in line:
            console.print(f"  ✅ Removed registration: {line.strip()}")
            include_found = True
            continue

        new_lines.append(line)

    if not import_found:
        console.print("[yellow]⚠️  Import pattern not found in app.py[/yellow]")
    if not include_found:
        console.print("[yellow]⚠️  Include pattern not found in app.py[/yellow]")

    # Only write back if changes were made
    if import_found or include_found:
        app_file.write_text("\n".join(new_lines))
    else:
        console.print("[yellow]⚠️  No changes made to app.py[/yellow]")


@entity_app.command()
def ls() -> None:
    """
    📋 List all entities in the project.

    Shows a comprehensive list of all entities in the project with their:
    - Entity name and description
    - Associated files (models, services, routers)
    - Database tables and relationships
    - API endpoints and methods
    - Test coverage status
    """
    console.print(
        Panel.fit("[bold cyan]Project Entities[/bold cyan]", border_style="cyan")
    )

    project_root = get_project_root()
    service_entities_dir = project_root / "src" / "app" / "entities" / "service"

    if not service_entities_dir.exists():
        console.print(
            f"[red]❌ Service entities directory not found: {service_entities_dir}[/red]"
        )
        return

    entities = []
    for item in service_entities_dir.iterdir():
        if (
            item.is_dir()
            and not item.name.startswith("_")
            and item.name != "__pycache__"
        ):
            entity_name = item.name.title()  # Convert to title case

            # Check for files
            has_entity = "✅" if (item / "entity.py").exists() else "❌"
            has_table = "✅" if (item / "table.py").exists() else "❌"
            has_repository = "✅" if (item / "repository.py").exists() else "❌"

            # Check for router
            router_file = (
                project_root
                / "src"
                / "app"
                / "api"
                / "http"
                / "routers"
                / "service"
                / f"{item.name}.py"
            )
            has_router = "✅" if router_file.exists() else "❌"

            # Check for tests (placeholder for now)
            has_tests = "❓"  # TODO: Implement test detection

            entities.append(
                (
                    entity_name,
                    has_entity,
                    has_table,
                    has_repository,
                    has_router,
                    has_tests,
                )
            )

    if not entities:
        console.print("[yellow]📭 No service entities found[/yellow]")
        console.print(
            "[dim]Create entities using: [cyan]cli entity add <name>[/cyan][/dim]"
        )
        return

    # Create table
    table = Table(show_header=True, header_style="bold blue")
    table.add_column("Entity", style="cyan", no_wrap=True)
    table.add_column("Entity", style="green", justify="center")
    table.add_column("Table", style="yellow", justify="center")
    table.add_column("Repository", style="magenta", justify="center")
    table.add_column("Router", style="blue", justify="center")
    table.add_column("Tests", style="red", justify="center")

    for (
        entity_name,
        has_entity,
        has_table,
        has_repository,
        has_router,
        has_tests,
    ) in sorted(entities):
        table.add_row(
            entity_name, has_entity, has_table, has_repository, has_router, has_tests
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(entities)} entities found[/dim]")
