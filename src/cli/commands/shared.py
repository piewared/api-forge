"""Shared utilities for CLI commands.

This module provides common utilities used across all command modules,
including console output, confirmation dialogs, and path resolution.
"""

from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

# Shared console instance for consistent output
console = Console()


def get_project_root() -> Path:
    """Get the project root directory.

    Walks up from the module location to find the project root,
    identified by the presence of pyproject.toml.

    Returns:
        Path to the project root directory
    """
    current = Path(__file__).resolve()

    # Walk up the directory tree looking for pyproject.toml
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent

    # Fallback to four levels up (src/cli/commands/shared.py -> project root)
    return Path(__file__).parent.parent.parent.parent


def confirm_action(
    action: str,
    details: str | None = None,
    extra_warning: str | None = None,
    force: bool = False,
) -> bool:
    """Prompt user to confirm a potentially destructive action.

    Args:
        action: Description of the action (e.g., "Stop all services")
        details: Additional details about what will be affected
        extra_warning: Extra warning message (e.g., for data loss)
        force: If True, skip the confirmation prompt

    Returns:
        True if the user confirmed, False otherwise
    """
    if force:
        return True

    # Build warning message
    warning_lines = [f"[bold red]⚠️  {action}[/bold red]"]

    if details:
        warning_lines.append(f"\n{details}")

    if extra_warning:
        warning_lines.append(f"\n[yellow]{extra_warning}[/yellow]")

    console.print(
        Panel(
            "\n".join(warning_lines),
            title="Confirmation Required",
            border_style="red",
        )
    )

    try:
        response = console.input(
            "\n[bold]Are you sure you want to proceed?[/bold] \\[y/N]: "
        )
        return response.strip().lower() in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        return False


# Alias for backward compatibility
confirm_destructive_action = confirm_action


def handle_error(message: str, details: str | None = None, exit_code: int = 1) -> None:
    """Handle an error by printing a message and exiting.

    Args:
        message: Error message to display
        details: Optional additional details
        exit_code: Exit code to use
    """
    console.print(f"\n[bold red]❌ {message}[/bold red]\n")
    if details:
        console.print(Panel(details, title="Details", border_style="red"))
    raise typer.Exit(exit_code)


def print_header(title: str, style: str = "blue") -> None:
    """Print a styled header panel.

    Args:
        title: Header title text
        style: Border style color
    """
    console.print(
        Panel.fit(
            f"[bold {style}]{title}[/bold {style}]",
            border_style=style,
        )
    )


def with_error_handling(func: Callable[..., None]) -> Callable[..., None]:
    """Decorator to wrap command functions with standard error handling.

    Catches common exceptions and formats them consistently.

    Args:
        func: The command function to wrap

    Returns:
        Wrapped function with error handling
    """
    from functools import wraps

    from src.cli.deployment.helm_deployer.image_builder import DeploymentError

    @wraps(func)
    def wrapper(*args: object, **kwargs: object) -> None:
        try:
            func(*args, **kwargs)
        except DeploymentError as e:
            handle_error(e.message, e.details)
        except KeyboardInterrupt:
            console.print("\n[dim]Operation cancelled by user.[/dim]")
            raise typer.Exit(130) from None

    return wrapper
