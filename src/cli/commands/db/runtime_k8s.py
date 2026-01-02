"""Kubernetes runtime for database workflows."""

from __future__ import annotations

from contextlib import AbstractContextManager

from src.cli.commands.db.runtime import DbRuntime
from src.cli.deployment.helm_deployer.deployer import get_deployer
from src.cli.deployment.status_display import is_temporal_enabled
from src.cli.shared.console import console
from src.infra.k8s import get_namespace, get_postgres_label
from src.infra.k8s.port_forward import postgres_port_forward_if_needed
from src.infra.k8s.postgres_connection import get_k8s_postgres_connection
from src.infra.postgres.connection import get_settings
from src.infra.utils.service_config import is_bundled_postgres_enabled
from src.utils.paths import get_project_root


def _port_forward() -> AbstractContextManager[None]:
    namespace = get_namespace()
    label = get_postgres_label()
    return postgres_port_forward_if_needed(namespace=namespace, pod_label=label)


def get_k8s_runtime() -> DbRuntime:
    """Build a DbRuntime for Kubernetes workflows."""
    project_root = get_project_root()
    return DbRuntime(
        name="k8s",
        console=console,
        get_settings=get_settings,
        connect=lambda settings, superuser: get_k8s_postgres_connection(
            settings, superuser_mode=superuser
        ),
        port_forward=_port_forward,
        get_deployer=get_deployer,
        secrets_dirs=[project_root / "infra" / "secrets" / "keys"],
        is_temporal_enabled=is_temporal_enabled,
        is_bundled_postgres_enabled=is_bundled_postgres_enabled,
    )
