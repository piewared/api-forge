"""Compose-based deployment runtime adapter.

Mirrors the ``DbRuntime`` pattern from ``src.cli.commands.db.runtime`` for
deployer/compose-runner factories. Each compose-based environment (dev,
prod) provides a factory that returns a frozen ``DeployRuntime`` whose
callables produce the environment-specific ``BaseDeployer`` and
``ComposeRunner`` instances.

This replaces the ``_get_deployer()`` / ``_get_compose_runner()`` private
factory functions that were duplicated across each environment's CLI
module. Typer command bodies remain in their own modules (typer's
introspection requires that), but the dependency-construction
boilerplate is consolidated.

K8s and Fly are intentionally not modeled here — their deployment surface
(helm vs fly machines) doesn't share the compose-runner shape, and
forcing optionality into the dataclass would weaken the abstraction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.cli.shared.compose import ComposeRunner
from src.cli.shared.console import CLIConsole, console
from src.utils.paths import get_project_root

if TYPE_CHECKING:
    from src.cli.deployment.base import BaseDeployer


@dataclass(frozen=True)
class DeployRuntime:
    """Environment-specific behaviors for compose-based deploy commands.

    Attributes:
        name: Short identifier (``"dev"`` or ``"prod"``).
        console: Rich-backed CLI console for output.
        project_root: Path to the project root.
        get_deployer: Callable that returns the environment's
            ``BaseDeployer`` subclass instance. Constructed lazily so
            simply having the runtime in scope doesn't force imports
            of heavyweight deployment infrastructure.
        get_compose_runner: Callable returning a ``ComposeRunner``
            preconfigured with the right compose file and project name.
    """

    name: str
    console: CLIConsole
    project_root: Path
    get_deployer: Callable[[], BaseDeployer]
    get_compose_runner: Callable[[], ComposeRunner]


def get_dev_runtime() -> DeployRuntime:
    """Build the dev (local Docker Compose) deployment runtime."""
    project_root = get_project_root()

    def _build_deployer() -> BaseDeployer:
        # Local import keeps DevDeployer's transitive deps off the cold path.
        from src.cli.deployment.dev_deployer import DevDeployer

        return DevDeployer(console, project_root)

    def _build_compose_runner() -> ComposeRunner:
        return ComposeRunner(
            project_root,
            compose_file=project_root / "docker-compose.dev.yml",
        )

    return DeployRuntime(
        name="dev",
        console=console,
        project_root=project_root,
        get_deployer=_build_deployer,
        get_compose_runner=_build_compose_runner,
    )


def get_prod_runtime() -> DeployRuntime:
    """Build the production Docker Compose deployment runtime."""
    project_root = get_project_root()

    def _build_deployer() -> BaseDeployer:
        from src.cli.deployment.prod_deployer import ProdDeployer

        return ProdDeployer(console, project_root)

    def _build_compose_runner() -> ComposeRunner:
        return ComposeRunner(
            project_root,
            compose_file=project_root / "docker-compose.prod.yml",
            project_name="api-forge-prod",
        )

    return DeployRuntime(
        name="prod",
        console=console,
        project_root=project_root,
        get_deployer=_build_deployer,
        get_compose_runner=_build_compose_runner,
    )
