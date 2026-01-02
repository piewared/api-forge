"""CLI context and dependency container."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import click
import typer

from src.cli.deployment.shell_commands import ShellCommands
from src.cli.shared.console import CLIConsole, console
from src.infra.constants import DeploymentConstants, DeploymentPaths
from src.infra.k8s import get_k8s_controller_sync
from src.infra.k8s.controller import KubernetesControllerSync
from src.utils.paths import get_project_root


@dataclass(frozen=True)
class CLIContext:
    """Runtime dependencies for CLI commands."""

    console: CLIConsole
    project_root: Path
    commands: ShellCommands
    k8s_controller: KubernetesControllerSync
    constants: DeploymentConstants
    paths: DeploymentPaths


def build_cli_context() -> CLIContext:
    """Build a fresh CLIContext."""
    project_root = get_project_root()
    constants = DeploymentConstants()
    paths = DeploymentPaths(project_root)

    return CLIContext(
        console=console,
        project_root=project_root,
        commands=ShellCommands(project_root),
        k8s_controller=get_k8s_controller_sync(),
        constants=constants,
        paths=paths,
    )


def get_cli_context(ctx: typer.Context | None = None) -> CLIContext:
    """Return the CLIContext from Typer, falling back to a new instance."""
    context = ctx or click.get_current_context(silent=True)
    if context and isinstance(context.obj, CLIContext):
        return context.obj
    return build_cli_context()
