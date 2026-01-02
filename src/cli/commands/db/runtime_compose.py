"""Docker Compose runtime for database workflows."""

from __future__ import annotations

from src.cli.commands.db.runtime import DbRuntime, no_port_forward
from src.cli.deployment.prod_deployer import get_deployer
from src.cli.deployment.status_display import is_temporal_enabled
from src.cli.shared.console import console
from src.infra.docker_compose.postgres_connection import (
    get_docker_compose_postgres_connection,
)
from src.infra.postgres.connection import get_settings
from src.infra.utils.service_config import is_bundled_postgres_enabled
from src.utils.paths import get_project_root


def get_compose_runtime() -> DbRuntime:
    """Build a DbRuntime for Docker Compose (prod) workflows."""
    project_root = get_project_root()
    return DbRuntime(
        name="compose",
        console=console,
        get_settings=get_settings,
        connect=lambda settings, superuser: get_docker_compose_postgres_connection(
            settings, superuser_mode=superuser
        ),
        port_forward=no_port_forward,
        get_deployer=get_deployer,
        secrets_dirs=[project_root / "infra" / "secrets" / "keys"],
        is_temporal_enabled=is_temporal_enabled,
        is_bundled_postgres_enabled=is_bundled_postgres_enabled,
    )
