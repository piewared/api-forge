"""Fly.io infrastructure abstraction layer.

This module provides a clean abstraction over Fly.io operations
via the flyctl CLI tool.

Example:
    from src.infra.flyio import FlyCtlController, FlyCtlControllerSync
    from src.utils.run_sync import run_sync

    # Async usage
    controller = FlyCtlController()
    if await controller.is_authenticated():
        clusters = await controller.mpg_list()
        for cluster in clusters:
            print(f"{cluster.name} ({cluster.region}): {cluster.status}")

    # Sync usage (for CLI commands)
    sync_controller = FlyCtlControllerSync()
    if sync_controller.is_authenticated():
        clusters = sync_controller.mpg_list()

    # Port forwarding for local development
    from src.infra.flyio import fly_postgres_port_forward_if_needed

    with fly_postgres_port_forward_if_needed("my-cluster"):
        # Connect to localhost:54321
        pass
"""

from .constants import FlyConstants
from .controller import (
    CommandResult,
    FlyAppInfo,
    FlyCtlController,
    FlyCtlControllerSync,
    ManagedPostgresInfo,
)
from .port_forward import (
    FlyPortForwardError,
    ensure_app_machines_running,
    fly_postgres_port_forward,
    fly_postgres_port_forward_if_needed,
    with_fly_postgres_port_forward,
)
from .temporal import (
    inject_temporal_fly_secrets,
    run_temporal_namespace_init,
    run_temporal_schema_setup,
)
from .url_utils import extract_pg_host_port

# Note: postgres_connection and db_settings are imported directly where needed
# to avoid circular imports
# from src.infra.flyio.postgres_connection import get_fly_postgres_connection
# from src.infra.flyio.db_settings import FlyDbSettings

__all__ = [
    # Controller classes
    "FlyCtlController",
    "FlyCtlControllerSync",
    # Data types
    "CommandResult",
    "FlyAppInfo",
    "ManagedPostgresInfo",
    # Constants
    "FlyConstants",
    # Port forwarding
    "FlyPortForwardError",
    "ensure_app_machines_running",
    "fly_postgres_port_forward",
    "fly_postgres_port_forward_if_needed",
    "with_fly_postgres_port_forward",
    # Temporal deployment helpers
    "inject_temporal_fly_secrets",
    "run_temporal_namespace_init",
    "run_temporal_schema_setup",
    # URL utilities
    "extract_pg_host_port",
    # Note: postgres_connection and db_settings classes imported directly where needed
]
