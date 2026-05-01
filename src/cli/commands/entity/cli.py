"""Entity management CLI commands."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from src.app.runtime.context import get_config
from src.cli.shared.console import console
from src.utils.paths import get_project_root

from .scaffold import (
    create_entity_files,
    get_entity_package_path,
    prompt_for_fields,
    sanitize_entity_name,
)

# Create the entity command group
entity_app = typer.Typer(help="🎭 Entity management commands")


@entity_app.command()
def add(
    entity_name: str = typer.Argument(None, help="Name of the entity to add"),
    with_workflow: str = typer.Option(
        None,
        "--with-workflow",
        help=(
            "Also scaffold a Temporal workflow with this name and wire it "
            "into the entity's service via a `dispatch()` method. Requires "
            "config.temporal.enabled=true."
        ),
    ),
) -> None:
    """
    ➕ Add a new entity to the project.

    Creates a new entity package with all the necessary files:
    - entity.py    — domain model with Pydantic validation
    - table.py     — SQLModel persistence model (auto-discovered for Alembic)
    - repository.py — data access layer
    - router.py    — CRUD endpoints (auto-discovered at app startup)
    - __init__.py  — package re-exports

    No edits to ``app.py`` are required: the router is registered automatically
    via :func:`register_entity_routers` at startup.
    """
    if not entity_name:
        entity_name = Prompt.ask("[cyan]Entity name")

    entity_name = sanitize_entity_name(entity_name)

    console.print(
        Panel.fit(
            f"[bold green]Adding Entity: {entity_name}[/bold green]",
            border_style="green",
        )
    )

    entity_package_path = get_entity_package_path(entity_name)

    if entity_package_path.exists():
        console.print(
            f"[red]❌ Entity '{entity_name}' already exists at {entity_package_path}[/red]"
        )
        raise typer.Exit(1)

    fields = prompt_for_fields()

    if not fields:
        console.print(
            "[yellow]⚠️ No fields defined. Creating entity with base fields only.[/yellow]"
        )

    console.print(f"\n[blue]Creating entity structure for: {entity_name}[/blue]")

    try:
        entity_package_path.mkdir(parents=True, exist_ok=True)

        console.print("[blue]📄 Creating entity files...[/blue]")
        create_entity_files(entity_name, fields, entity_package_path)

        console.print(
            f"\n[green]✅ Entity '{entity_name}' created successfully![/green]"
        )
        console.print("\n[blue]📄 Files created:[/blue]")
        for filename in (
            "entity.py",
            "table.py",
            "repository.py",
            "schemas.py",
            "service.py",
            "router.py",
            "__init__.py",
        ):
            console.print(f"  - {entity_package_path / filename}")

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

        # Optionally scaffold a workflow + wire a dispatch() method on the
        # entity service. Done at the end so a workflow failure doesn't
        # leave the entity half-scaffolded.
        if with_workflow:
            _scaffold_and_wire_workflow(entity_name, with_workflow)

        console.print(
            "\n[dim]💡 Restart your dev server to pick up the new router.[/dim]"
        )

    except Exception as e:
        console.print(f"[red]❌ Error creating entity: {e}[/red]")
        if entity_package_path.exists():
            import shutil

            shutil.rmtree(entity_package_path)
        raise typer.Exit(1) from e


def _scaffold_and_wire_workflow(entity_name: str, workflow_name: str) -> None:
    """Generate a workflow + insert a ``dispatch()`` method into the entity's
    service that starts it. Surfaces the canonical wiring (TemporalClientService
    + BaseWorkflow.start_workflow + idempotent ID) so newcomers don't have to
    hunt for the pattern.
    """
    if not get_config().temporal.enabled:
        console.error(
            "--with-workflow requires Temporal to be enabled "
            "(config.temporal.enabled=true)."
        )
        console.print(
            "  Either flip the config flag, or use FastAPI BackgroundTasks "
            "for fire-and-forget async work."
        )
        raise typer.Exit(2)

    # Defer the imports so users without Temporal don't pay them on every
    # ``entity add`` invocation.
    from src.cli.commands.workflow.scaffold import (
        create_workflow_files,
        sanitize_workflow_name,
    )

    workflow_name = sanitize_workflow_name(workflow_name)
    console.print(
        f"\n[blue]🔄 Scaffolding workflow {workflow_name} for {entity_name}...[/blue]"
    )

    # The workflow takes the entity's id as a single typed input.
    fields = [{"name": f"{entity_name.lower()}_id", "type": "str", "optional": False}]
    wf_path, wf_test_path = create_workflow_files(workflow_name, fields)

    console.ok(f"Workflow scaffolded: {wf_path}")
    console.ok(f"Workflow test:       {wf_test_path}")

    # Inject a dispatch() method into the entity's service.py.
    service_path = (
        get_project_root()
        / "src"
        / "app"
        / "entities"
        / "service"
        / entity_name.lower()
        / "service.py"
    )
    if not service_path.exists():
        console.warn(
            f"Couldn't find {service_path} — skipping dispatch() injection. "
            f"Wire the workflow manually using {workflow_name}Workflow.start_workflow(...)."
        )
        return

    dispatch_block = f'''

    async def dispatch(self, {entity_name.lower()}_id: str) -> str:
        """Dispatch a {workflow_name} workflow for this {entity_name.lower()}.

        Canonical pattern: domain endpoint → service → workflow start.
        Returns the workflow handle's ID so callers can poll/signal later.
        Idempotent on (entity_id), so retries dedupe via the workflow ID.
        """
        from src.app.core.services import TemporalClientService
        from src.app.worker.workflows.{workflow_name.lower()} import (
            {workflow_name}Input,
            {workflow_name}Workflow,
        )

        # NB: ``TemporalClientService`` should be injected via the service's
        # ``__init__`` (see docs/fastapi-temporal-workflows.md). Replace the
        # placeholder access below with your dependency-injected instance.
        temporal: TemporalClientService = self._temporal  # type: ignore[attr-defined]
        client = await temporal.get_client()
        handle = await {workflow_name}Workflow.start_workflow(
            client,
            input={workflow_name}Input({entity_name.lower()}_id={entity_name.lower()}_id),
            id=f"{workflow_name.lower()}-{{{entity_name.lower()}_id}}",  # idempotent
        )
        return handle.id
'''
    service_path.write_text(service_path.read_text().rstrip() + dispatch_block + "\n")
    console.ok(f"Wired dispatch() into {service_path.relative_to(get_project_root())}")
    console.print(
        "  [dim]Note: inject TemporalClientService via the service's __init__ — "
        "the generated dispatch() expects ``self._temporal``.[/dim]"
    )


@entity_app.command()
def rm(
    entity_name: str = typer.Argument(..., help="Name of the entity to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """
    🗑️  Remove an entity from the project.

    Deletes the entire entity package directory. Auto-discovery means no
    edits to ``app.py`` are required — the router disappears with the
    package.
    """
    entity_name = sanitize_entity_name(entity_name)

    console.print(
        Panel.fit(
            f"[bold red]Removing Entity: {entity_name}[/bold red]",
            border_style="red",
        )
    )

    try:
        entity_package_path = get_entity_package_path(entity_name)

        if not entity_package_path.exists():
            console.print(f"[red]❌ Entity '{entity_name}' does not exist[/red]")
            raise typer.Exit(1)

        console.print("\n[yellow]📂 Directory to be removed:[/yellow]")
        console.print(f"  📁 {entity_package_path}/")

        if not force:
            console.print("\n[red bold]⚠️  This action cannot be undone![/red bold]")
            confirm = typer.confirm("Are you sure you want to remove this entity?")
            if not confirm:
                console.print("[blue]Operation cancelled.[/blue]")
                return

        console.print("\n[blue]🗑️  Removing entity package...[/blue]")
        import shutil

        shutil.rmtree(entity_package_path)
        console.print(f"  ✅ Removed entity package: {entity_package_path}")

        console.print(
            f"\n[green]✅ Entity '{entity_name}' removed successfully![/green]"
        )
        console.print(
            "\n[dim]💡 Restart your dev server to drop the removed router.[/dim]"
        )

    except Exception as e:
        console.print(f"[red]❌ Error removing entity: {e}[/red]")
        raise typer.Exit(1) from e


@entity_app.command()
def ls() -> None:
    """
    📋 List all entities in the project.

    Shows each entity package and which expected files it has — the router
    column reflects what auto-discovery will pick up at app startup.
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
            entity_name = item.name.title()

            has_entity = "✅" if (item / "entity.py").exists() else "❌"
            has_table = "✅" if (item / "table.py").exists() else "❌"
            has_repository = "✅" if (item / "repository.py").exists() else "❌"
            has_router = "✅" if (item / "router.py").exists() else "❌"

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
