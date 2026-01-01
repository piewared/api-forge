"""Shared utilities for CLI commands.

This module provides common utilities used across all command modules,
including console output, confirmation dialogs, and path resolution.
"""

from collections.abc import Callable
from typing import Literal

import typer
from rich.console import Console, ConsoleRenderable
from rich.panel import Panel
from rich.status import Status


class CLIConsole:
    """Rich console wrapper for consistent CLI output."""

    def __init__(self) -> None:
        """Initialize the CLI console."""
        self.console = Console()

    def print(self, msg: ConsoleRenderable | str | None = None) -> None:
        self.console.print(msg)

    def status(self, status: str) -> Status:
        return self.console.status(status)

    def info(self, msg: str) -> None:
        self.console.print(f"[cyan]ℹ[/cyan]  {msg}")

    def ok(self, msg: str) -> None:
        self.console.print(f"[green]✅[/green] {msg}")

    def error(self, msg: str) -> None:
        self.console.print(f"[red]❌[/red] {msg}")

    def warn(self, msg: str) -> None:
        self.console.print(f"[yellow]⚠️[/yellow]  {msg}")

    def confirm_action(
        self,
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

        self.console.print(
            Panel(
                "\n".join(warning_lines),
                title="Confirmation Required",
                border_style="red",
            )
        )

        try:
            response = self.console.input(
                "\n[bold]Are you sure you want to proceed?[/bold] \\[y/N]: "
            )
            return response.strip().lower() in ("y", "yes")
        except (KeyboardInterrupt, EOFError):
            self.console.print("\n[dim]Cancelled.[/dim]")
            return False

    def handle_error(
        self, message: str, details: str | None = None, exit_code: int = 1
    ) -> None:
        """Handle an error by printing a message and exiting.

        Args:
            message: Error message to display
            details: Optional additional details
            exit_code: Exit code to use
        """
        self.error(f"\n[bold red]❌ {message}[/bold red]\n")
        if details:
            self.console.print(Panel(details, title="Details", border_style="red"))
        raise typer.Exit(exit_code)

    def prompt_choice(
        self,
        title: str,
        choices: list[tuple[str, str]],
        *,
        default: int = 1,
        cancel_option: bool = True,
    ) -> int:
        """Prompt user to select from numbered choices.

        Args:
            title: Title/question to display
            choices: List of (short_name, description) tuples
            default: Default choice (1-indexed)
            cancel_option: Whether to add a cancel option

        Returns:
            Selected choice number (1-indexed), or 0 if cancelled
        """
        self.console.print(f"\n[yellow]{title}[/yellow]\n")

        # Display numbered options
        for i, (name, description) in enumerate(choices, 1):
            marker = "[bold cyan]→[/bold cyan]" if i == default else " "
            self.console.print(f"  {marker} [bold]{i}.[/bold] {name}")
            if description:
                self.console.print(f"       [dim]{description}[/dim]")

        if cancel_option:
            self.console.print("  [bold]0.[/bold] Cancel")

        try:
            while True:
                response = self.console.input(f"\nEnter choice [{default}]: ").strip()

                if not response:
                    return default

                if response == "0" and cancel_option:
                    self.console.print("[dim]Cancelled.[/dim]")
                    return 0

                try:
                    choice = int(response)
                    if 1 <= choice <= len(choices):
                        return choice
                    self.console.print(
                        f"[red]Please enter a number between 1 and {len(choices)}[/red]"
                    )
                except ValueError:
                    self.console.print("[red]Please enter a valid number[/red]")

        except (KeyboardInterrupt, EOFError):
            self.console.print("\n[dim]Cancelled.[/dim]")
            return 0

    def prompt_resource_conflict(
        self,
        resource_type: str,
        resource_name: str,
        namespace: str,
        *,
        reason: str = "immutable fields changed",
        data_warning: bool = True,
    ) -> Literal["recreate", "skip", "cancel"]:
        """Prompt user to handle a Kubernetes resource update conflict.

        This handles cases where a resource (StatefulSet, etc.) cannot be
        updated in-place due to immutable field changes.

        Args:
            resource_type: Type of resource (e.g., "StatefulSet", "Deployment")
            resource_name: Name of the resource
            namespace: Kubernetes namespace
            reason: Why the update failed
            data_warning: Whether to warn about potential data loss

        Returns:
            One of: "recreate", "skip", or "cancel"
        """
        self.warn(f"{resource_type} update failed - {reason}")
        self.console.print(
            f"\n[dim]{resource_type}s have immutable fields that cannot be updated in-place.[/dim]"
        )
        self.console.print(
            "[dim]To apply these changes, the resource must be deleted and recreated.[/dim]"
        )

        choices = [
            (
                "Delete and recreate",
                "PVCs retained, but Helm release history will be reset"
                if data_warning
                else "Resource will be recreated, Helm history reset",
            ),
            ("Skip", f"Keep existing {resource_type.lower()}"),
        ]

        choice = self.prompt_choice(
            f"How would you like to proceed with {resource_name}?",
            choices,
            default=1,  # Default to recreate (user's intent)
            cancel_option=True,
        )

        if choice == 1:
            return "recreate"
        elif choice == 2:
            return "skip"
        else:
            return "cancel"

    def print_header(self, title: str, style: str = "blue") -> None:
        """Print a styled header panel.

        Args:
            title: Header title text
            style: Border style color
        """
        self.console.print(
            Panel.fit(
                f"[bold {style}]{title}[/bold {style}]",
                border_style=style,
            )
        )

    def print_subheader(self, title: str) -> None:
        """Print a subheader.

        Args:
            title: Subheader title text
        """
        self.console.print(f"\n[bold underline]{title}[/bold underline]\n")


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
            console.handle_error(e.message, e.details)
        except KeyboardInterrupt:
            console.print("\n[dim]Operation cancelled by user.[/dim]")
            raise typer.Exit(130) from None

    return wrapper


# Shared console instance for consistent output
console = CLIConsole()
