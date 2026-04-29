"""Shared Fly.io prerequisites and controller access.

Consolidates the duplicated _get_fly_controller, _check_flyctl_installed,
_check_authenticated, and _check_prerequisites that were copy-pasted across
fly/, fly_db/, fly_auth, and fks modules.
"""

import typer

from src.cli.shared.console import console
from src.infra.flyio import FlyCtlControllerSync


def get_fly_controller() -> FlyCtlControllerSync:
    """Get Fly.io controller instance."""
    return FlyCtlControllerSync()


def check_flyctl_installed(controller: FlyCtlControllerSync) -> None:
    """Check if flyctl is installed and show error if not."""
    if not controller.is_installed():
        console.error("flyctl CLI is not installed.")
        console.info("Install from: https://fly.io/docs/flyctl/install/")
        console.info("  curl -L https://fly.io/install.sh | sh")
        raise typer.Exit(1)


def check_authenticated(controller: FlyCtlControllerSync) -> None:
    """Check if user is authenticated to Fly.io."""
    if not controller.is_authenticated():
        console.error("Not logged in to Fly.io")
        console.info("Run: api-forge-cli fly auth login")
        raise typer.Exit(1)


def check_prerequisites(controller: FlyCtlControllerSync) -> None:
    """Check that flyctl is installed and user is authenticated."""
    check_flyctl_installed(controller)
    check_authenticated(controller)
