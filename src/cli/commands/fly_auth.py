"""Fly.io authentication commands.

Provides login, logout, and whoami commands for Fly.io authentication.
"""

from typing import Annotated

import typer

from src.cli.shared.console import console
from src.cli.shared.fly import check_flyctl_installed, get_fly_controller

# ---------------------------------------------------------------------------
# Typer App
# ---------------------------------------------------------------------------

fly_auth_app = typer.Typer(
    name="auth",
    help="Fly.io authentication commands.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@fly_auth_app.command()
def login(
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            "-i",
            help="Use email/password instead of browser-based login.",
        ),
    ] = False,
) -> None:
    """Log in to Fly.io.

    Opens a browser for authentication by default.
    Use --interactive for email/password login.
    """
    controller = get_fly_controller()
    check_flyctl_installed(controller)

    console.print_header("Fly.io Authentication")

    # Check if already logged in
    is_auth, email = controller.auth_whoami()
    if is_auth:
        console.info(f"Already logged in as: [cyan]{email}[/cyan]")
        if not typer.confirm("Log in as a different user?", default=False):
            return

    # Perform login
    login_method = "email/password" if interactive else "browser"
    console.info(f"Starting {login_method} authentication...")

    result = controller.auth_login(interactive=interactive)

    if result.success:
        # Verify login succeeded
        is_auth, email = controller.auth_whoami()
        if is_auth:
            console.ok(f"Successfully logged in as: [cyan]{email}[/cyan]")
        else:
            console.ok("Login completed.")
    else:
        console.error("Login failed.")
        if result.stderr:
            console.print(f"[dim]{result.stderr}[/dim]")
        raise typer.Exit(1)


@fly_auth_app.command()
def logout() -> None:
    """Log out from Fly.io.

    Removes local authentication credentials.
    """
    controller = get_fly_controller()
    check_flyctl_installed(controller)

    console.print_header("Fly.io Logout")

    # Check if logged in
    is_auth, email = controller.auth_whoami()
    if not is_auth:
        console.info("Not currently logged in.")
        return

    console.info(f"Logging out user: [cyan]{email}[/cyan]")

    result = controller.auth_logout()

    if result.success:
        console.ok("Successfully logged out.")
    else:
        console.error("Logout failed.")
        if result.stderr:
            console.print(f"[dim]{result.stderr}[/dim]")
        raise typer.Exit(1)


@fly_auth_app.command()
def whoami() -> None:
    """Show current Fly.io user.

    Displays the email of the currently authenticated user.
    """
    controller = get_fly_controller()
    check_flyctl_installed(controller)

    is_auth, result = controller.auth_whoami()

    if is_auth:
        console.ok(f"Logged in as: [cyan]{result}[/cyan]")
    else:
        console.warn("Not logged in to Fly.io")
        console.info("Run [green]api-forge-cli fly auth login[/green] to authenticate.")
        raise typer.Exit(1)


@fly_auth_app.command()
def status() -> None:
    """Show Fly.io authentication status with details.

    Displays authentication status and account information.
    """
    from rich.table import Table

    controller = get_fly_controller()
    check_flyctl_installed(controller)

    console.print_header("Fly.io Authentication Status")

    # Check authentication
    is_auth, email = controller.auth_whoami()

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="dim")
    table.add_column("Value")

    if is_auth:
        table.add_row("Status", "[green]Authenticated[/green]")
        table.add_row("User", f"[cyan]{email}[/cyan]")

        # Try to get token (just check if it exists)
        has_token, _ = controller.auth_token()
        table.add_row(
            "Token", "[green]Valid[/green]" if has_token else "[yellow]Unknown[/yellow]"
        )
    else:
        table.add_row("Status", "[red]Not authenticated[/red]")
        table.add_row("", "")
        table.add_row(
            "", "[dim]Run 'api-forge-cli fly auth login' to authenticate[/dim]"
        )

    console.print(table)
