"""Utility functions for handling secrets."""

import getpass
import os

import typer

from src.cli.shared.console import console


def get_password(prompt: str, env_var: str | None = None) -> str:
    """Get password from environment or prompt user."""
    if env_var:
        password = os.environ.get(env_var)
        if password:
            console.print(f"[dim]Using password from {env_var}[/dim]")
            return password
        else:
            console.print(f"[dim]Environment variable {env_var} not set[/dim]")

    try:
        password = getpass.getpass(prompt)
        if not password:
            console.print("[red]❌ No password entered[/red]")
            raise typer.Exit(1) from None
        return password
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Password input cancelled[/dim]")
        raise typer.Exit(1) from None
