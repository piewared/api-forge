"""Docker Compose runtime for database workflows."""

from __future__ import annotations

from src.cli.commands.db.runtime import DbRuntime, no_port_forward
from src.cli.deployment.prod_deployer import get_deployer
from src.cli.deployment.status_display import is_temporal_enabled
from src.cli.shared.config import get_db_settings
from src.cli.shared.console import console
from src.infra.docker_compose.postgres_connection import (
    get_docker_compose_postgres_connection,
)
from src.infra.secrets import get_secrets_manager
from src.infra.utils.service_config import is_bundled_postgres_enabled


def get_compose_runtime() -> DbRuntime:
    """Build a DbRuntime for Docker Compose (prod) workflows."""
    return DbRuntime(
        name="compose",
        console=console,
        get_settings=get_db_settings,
        connect=lambda settings, superuser: get_docker_compose_postgres_connection(
            settings, superuser_mode=superuser
        ),
        port_forward=no_port_forward,
        get_deployer=get_deployer,
        secrets_manager=get_secrets_manager(),
        is_temporal_enabled=is_temporal_enabled,
        is_bundled_postgres_enabled=is_bundled_postgres_enabled,
    )
