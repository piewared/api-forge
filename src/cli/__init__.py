"""Main CLI application module.

This module provides the main entry point for the API Forge CLI.
Commands are organized by deployment target (dev, prod, k8s, fly)
rather than by operation type (up, down, status).

Command Groups:
- dev: Development Docker Compose environment
- prod: Production Docker Compose deployment (includes 'prod db' subcommands)
- k8s: Kubernetes Helm deployment (includes 'k8s db' subcommands)
- fly: Fly.io deployment (traditional Fly Machines)
- entity: Entity/model scaffolding
- secrets: Secret management
- users: Keycloak user management (dev)
"""

import typer

from .commands import (
    activity_app,
    config_app,
    dev_app,
    entity_app,
    fly_app,
    k8s_app,
    prod_app,
    secrets_app,
    update_app,
    users_app,
    workflow_app,
)
from .context import build_cli_context

# Create the main CLI application
app = typer.Typer(
    help="🛠️  API Forge CLI - Development and Deployment Tool",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.callback()
def _configure_context(ctx: typer.Context) -> None:
    """Attach runtime dependencies to the CLI context."""
    if ctx.obj is None:
        ctx.obj = build_cli_context()


# Register deployment target command groups
app.add_typer(dev_app, name="dev", help="Development environment commands")
app.add_typer(prod_app, name="prod", help="Production Docker Compose commands")
app.add_typer(k8s_app, name="k8s", help="Kubernetes Helm deployment commands")
app.add_typer(fly_app, name="fly", help="Fly.io deployment commands")

# Register utility command groups
app.add_typer(config_app, name="config", help="Configuration validation")
app.add_typer(entity_app, name="entity")
app.add_typer(workflow_app, name="workflow")
app.add_typer(activity_app, name="activity")
app.add_typer(secrets_app, name="secrets")
app.add_typer(update_app, name="update")
app.add_typer(users_app, name="users")


def main() -> None:
    """Main entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
