"""Fly.io Kubernetes (FKS) deployment commands.

This module provides a placeholder for future Fly.io Kubernetes Service
deployment commands. FKS is currently in beta and not yet fully supported.

See docs/fastapi-flyio-kubernetes.md for compatibility analysis.
"""

from typing import Annotated

import typer

from src.cli.shared.console import console

# ---------------------------------------------------------------------------
# Typer App
# ---------------------------------------------------------------------------

fly_app = typer.Typer(
    name="fly",
    help="Fly.io Kubernetes (FKS) deployment commands (coming soon).",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@fly_app.command()
def up(
    cluster: Annotated[
        str | None,
        typer.Option(
            "--cluster",
            "-c",
            help="FKS cluster name",
        ),
    ] = None,
) -> None:
    """Deploy to Fly.io Kubernetes Service (coming soon).

    This command is a placeholder for future FKS deployment support.
    FKS is currently in beta with some limitations for our use case.

    See docs/fastapi-flyio-kubernetes.md for details.
    """
    console.print_header("Fly.io Kubernetes Deployment")
    _show_coming_soon_message()


@fly_app.command()
def down(
    cluster: Annotated[
        str | None,
        typer.Option(
            "--cluster",
            "-c",
            help="FKS cluster name",
        ),
    ] = None,
) -> None:
    """Remove Fly.io Kubernetes deployment (coming soon).

    This command is a placeholder for future FKS deployment support.
    """
    console.print_header("Removing Fly.io Deployment")
    _show_coming_soon_message()


@fly_app.command()
def status(
    cluster: Annotated[
        str | None,
        typer.Option(
            "--cluster",
            "-c",
            help="FKS cluster name",
        ),
    ] = None,
) -> None:
    """Show Fly.io Kubernetes deployment status (coming soon).

    This command is a placeholder for future FKS deployment support.
    """
    console.print_header("Fly.io Deployment Status")
    _show_coming_soon_message()


@fly_app.command()
def clusters() -> None:
    """List available FKS clusters (coming soon).

    This command is a placeholder for future FKS support.
    """
    console.print_header("FKS Clusters")
    _show_coming_soon_message()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _show_coming_soon_message() -> None:
    """Display the coming soon message with context."""
    from rich.panel import Panel

    message = """[yellow]Fly.io Kubernetes Service (FKS) support is planned but not yet implemented.[/yellow]

[bold cyan]Current Status:[/bold cyan]
• FKS is in public beta
• Some features we need (e.g., Ingress) require workarounds
• We're monitoring FKS development for GA readiness

[bold cyan]Key Differences from Standard K8s:[/bold cyan]
• Uses LoadBalancer instead of Ingress for external access
• No built-in Ingress controller
• Uses Fly.io's global edge network for routing
• Requires flyctl for cluster management

[bold cyan]Next Steps:[/bold cyan]
1. Review compatibility analysis: docs/fastapi-flyio-kubernetes.md
2. For standard Kubernetes, use: [green]uv run api-forge-cli k8s up[/green]
3. For Docker Compose production: [green]uv run api-forge-cli prod up[/green]

[dim]Want to help implement FKS support? Contributions welcome![/dim]"""

    console.print(Panel(message, title="Coming Soon", border_style="yellow"))
