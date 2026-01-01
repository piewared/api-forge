"""Database runtime adapters for CLI workflows."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.cli.shared.console import CLIConsole
from src.infra.postgres import PostgresConnection


@dataclass(frozen=True)
class DbRuntime:
    """Environment-specific behaviors for database workflows."""

    name: str
    console: CLIConsole
    get_settings: Callable[[], Any]
    connect: Callable[[Any, bool], PostgresConnection]
    port_forward: Callable[[], AbstractContextManager[None]]
    get_deployer: Callable[[], Any]
    secrets_dirs: Sequence[Path]
    is_temporal_enabled: Callable[[], bool]
    is_bundled_postgres_enabled: Callable[[], bool]


def no_port_forward() -> AbstractContextManager[None]:
    """No-op context manager for environments without port forwarding."""
    return nullcontext()
