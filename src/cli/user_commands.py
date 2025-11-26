"""Keycloak user management CLI commands."""

import typer
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from src.dev.keycloak_client import KeycloakClient

console = Console()

# Create the users subcommand app
users_app = typer.Typer(help="Manage Keycloak users in development environment")


def get_keycloak_client() -> KeycloakClient:
    """Get an authenticated Keycloak client."""
    client = KeycloakClient("http://localhost:8080")
    try:
        client.authenticate("admin", "admin")
        return client
    except Exception as e:
        console.print(f"[red]❌ Failed to connect to Keycloak: {e}[/red]")
        raise typer.Exit(code=1) from e


@users_app.command("list")
def list_users(
    realm: str = typer.Option(
        "test-realm", "--realm", "-r", help="Keycloak realm name"
    ),
    limit: int = typer.Option(
        100, "--limit", "-l", help="Maximum number of users to show"
    ),
) -> None:
    """List all users in the Keycloak realm."""
    client = get_keycloak_client()

    try:
        users = client.get_users(realm, limit=limit)

        if not users:
            console.print(f"[yellow]No users found in realm '{realm}'[/yellow]")
            return

        table = Table(title=f"Users in realm '{realm}'")
        table.add_column("ID", style="cyan")
        table.add_column("Username", style="green")
        table.add_column("Email", style="blue")
        table.add_column("First Name", style="magenta")
        table.add_column("Last Name", style="magenta")
        table.add_column("Enabled", style="yellow")

        for user in users:
            table.add_row(
                user.get("id", ""),
                user.get("username", ""),
                user.get("email", ""),
                user.get("firstName", ""),
                user.get("lastName", ""),
                "✅" if user.get("enabled", False) else "❌",
            )

        console.print(table)
        console.print(f"\n[green]Found {len(users)} users[/green]")

    except Exception as e:
        console.print(f"[red]❌ Failed to list users: {e}[/red]")
        raise typer.Exit(code=1) from e


@users_app.command("add")
def add_user(
    username: str = typer.Argument(..., help="Username for the new user"),
    email: str = typer.Option(..., "--email", "-e", help="Email address"),
    password: str = typer.Option(..., "--password", "-p", help="Password"),
    first_name: str = typer.Option("", "--first-name", "-f", help="First name"),
    last_name: str = typer.Option("", "--last-name", "-l", help="Last name"),
    realm: str = typer.Option(
        "test-realm", "--realm", "-r", help="Keycloak realm name"
    ),
    enabled: bool = typer.Option(True, "--enabled/--disabled", help="Enable the user"),
    temporary_password: bool = typer.Option(
        False, "--temporary/--permanent", help="Require password change on first login"
    ),
) -> None:
    """Add a new user to the Keycloak realm."""
    client = get_keycloak_client()

    try:
        # Check if user already exists
        if client.user_exists(realm, username):
            console.print(
                f"[red]❌ User '{username}' already exists in realm '{realm}'[/red]"
            )
            raise typer.Exit(code=1)

        user_data = {
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": enabled,
            "emailVerified": True,
            "credentials": [
                {
                    "type": "password",
                    "value": password,
                    "temporary": temporary_password,
                }
            ],
        }

        if client.create_user(realm, user_data):
            console.print(
                f"[green]✅ Successfully created user '{username}' in realm '{realm}'[/green]"
            )
        else:
            console.print(f"[red]❌ Failed to create user '{username}'[/red]")
            raise typer.Exit(code=1)

    except Exception as e:
        console.print(f"[red]❌ Failed to create user: {e}[/red]")
        raise typer.Exit(code=1) from e


@users_app.command("delete")
def delete_user(
    username: str = typer.Argument(..., help="Username to delete"),
    realm: str = typer.Option(
        "test-realm", "--realm", "-r", help="Keycloak realm name"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Delete a user from the Keycloak realm."""
    client = get_keycloak_client()

    try:
        # Get user details
        user = client.get_user_by_username(realm, username)
        if not user:
            console.print(
                f"[red]❌ User '{username}' not found in realm '{realm}'[/red]"
            )
            raise typer.Exit(code=1)

        # Confirm deletion unless --force is used
        if not force:
            user_info = (
                f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
            )
            if user_info:
                user_info = f" ({user_info})"

            if not Confirm.ask(
                f"Are you sure you want to delete user '{username}'{user_info}?"
            ):
                console.print("[yellow]Deletion cancelled[/yellow]")
                return

        # Delete the user
        if client.delete_user(realm, user["id"]):
            console.print(
                f"[green]✅ Successfully deleted user '{username}' from realm '{realm}'[/green]"
            )
        else:
            console.print(f"[red]❌ Failed to delete user '{username}'[/red]")
            raise typer.Exit(code=1)

    except Exception as e:
        console.print(f"[red]❌ Failed to delete user: {e}[/red]")
        raise typer.Exit(code=1) from e


@users_app.command("info")
def user_info(
    username: str = typer.Argument(..., help="Username to get info for"),
    realm: str = typer.Option(
        "test-realm", "--realm", "-r", help="Keycloak realm name"
    ),
) -> None:
    """Show detailed information about a user."""
    client = get_keycloak_client()

    try:
        user = client.get_user_by_username(realm, username)
        if not user:
            console.print(
                f"[red]❌ User '{username}' not found in realm '{realm}'[/red]"
            )
            raise typer.Exit(code=1)

        table = Table(title=f"User Information: {username}")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="white")

        # Basic information
        table.add_row("ID", user.get("id", ""))
        table.add_row("Username", user.get("username", ""))
        table.add_row("Email", user.get("email", ""))
        table.add_row("First Name", user.get("firstName", ""))
        table.add_row("Last Name", user.get("lastName", ""))
        table.add_row("Enabled", "✅" if user.get("enabled", False) else "❌")
        table.add_row(
            "Email Verified", "✅" if user.get("emailVerified", False) else "❌"
        )
        table.add_row("Created", str(user.get("createdTimestamp", "")))

        console.print(table)

    except Exception as e:
        console.print(f"[red]❌ Failed to get user info: {e}[/red]")
        raise typer.Exit(code=1) from e


@users_app.command("reset-password")
def reset_password(
    username: str = typer.Argument(..., help="Username to reset password for"),
    password: str = typer.Option(..., "--password", "-p", help="New password"),
    realm: str = typer.Option(
        "test-realm", "--realm", "-r", help="Keycloak realm name"
    ),
    temporary: bool = typer.Option(
        False, "--temporary", "-t", help="Require password change on next login"
    ),
) -> None:
    """Reset a user's password."""
    client = get_keycloak_client()

    try:
        # Get user details
        user = client.get_user_by_username(realm, username)
        if not user:
            console.print(
                f"[red]❌ User '{username}' not found in realm '{realm}'[/red]"
            )
            raise typer.Exit(code=1)

        # Reset password
        if client.reset_user_password(realm, user["id"], password, temporary):
            temp_msg = " (temporary)" if temporary else ""
            console.print(
                f"[green]✅ Successfully reset password for user '{username}'{temp_msg}[/green]"
            )
        else:
            console.print(
                f"[red]❌ Failed to reset password for user '{username}'[/red]"
            )
            raise typer.Exit(code=1)

    except Exception as e:
        console.print(f"[red]❌ Failed to reset password: {e}[/red]")
        raise typer.Exit(code=1) from e
