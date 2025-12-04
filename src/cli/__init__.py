"""Main CLI application module.

This module provides the main entry point for the API Forge CLI.
Commands are organized by deployment target (dev, prod, k8s, fly)
rather than by operation type (up, down, status).

Command Groups:
- dev: Development Docker Compose environment
- prod: Production Docker Compose deployment
- k8s: Kubernetes Helm deployment
- fly: Fly.io Kubernetes (coming soon)
- entity: Entity/model scaffolding
- secrets: Secret management
- users: Keycloak user management (dev)
"""

import typer

from .commands import (
    dev_app,
    entity_app,
    fly_app,
    k8s_app,
    prod_app,
    secrets_app,
    users_app,
)

# Create the main CLI application
app = typer.Typer(
    help="🛠️  API Forge CLI - Development and Deployment Tool",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Register deployment target command groups
app.add_typer(dev_app, name="dev", help="Development environment commands")
app.add_typer(prod_app, name="prod", help="Production Docker Compose commands")
app.add_typer(k8s_app, name="k8s", help="Kubernetes Helm deployment commands")
app.add_typer(fly_app, name="fly", help="Fly.io Kubernetes commands (coming soon)")

# Register utility command groups
app.add_typer(entity_app, name="entity")
app.add_typer(secrets_app, name="secrets")
app.add_typer(users_app, name="users")


def main() -> None:
    """Main entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
