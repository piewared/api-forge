"""Kubernetes runtime for database workflows."""

from __future__ import annotations

import time
from contextlib import AbstractContextManager
from typing import Any

from src.cli.commands.db.runtime import DbRuntime
from src.cli.deployment.helm_deployer.deployer import get_deployer
from src.cli.deployment.status_display import is_temporal_enabled
from src.cli.shared.config import get_db_settings
from src.cli.shared.console import console
from src.infra.k8s import get_namespace, get_postgres_label
from src.infra.k8s.port_forward import postgres_port_forward_if_needed
from src.infra.k8s.postgres_connection import get_k8s_postgres_connection
from src.infra.secrets import get_secrets_manager
from src.infra.utils.service_config import is_bundled_postgres_enabled


def _port_forward() -> AbstractContextManager[None]:
    namespace = get_namespace()
    label = get_postgres_label()
    return postgres_port_forward_if_needed(namespace=namespace, pod_label=label)


def get_k8s_runtime() -> DbRuntime:
    """Build a DbRuntime for Kubernetes workflows."""
    return DbRuntime(
        name="k8s",
        console=console,
        get_settings=get_db_settings,
        connect=lambda settings, superuser: get_k8s_postgres_connection(
            settings, superuser_mode=superuser
        ),
        port_forward=_port_forward,
        get_deployer=get_deployer,
        secrets_manager=get_secrets_manager(),
        is_temporal_enabled=is_temporal_enabled,
        is_bundled_postgres_enabled=is_bundled_postgres_enabled,
    )


def resolve_statefulset_conflict(
    controller: Any,
    resource_name: str,
    namespace: str,
    pod_label: str,
) -> bool:
    """Delete a conflicting StatefulSet and clean up for fresh Helm install.

    Handles the common scenario where a Helm upgrade fails because of immutable
    field changes in a StatefulSet spec. Performs orphan cascade deletion to
    preserve PVCs (and thus data), deletes orphaned pods, and clears Helm
    release metadata so the next `helm upgrade --install` starts fresh.

    Args:
        controller: KubernetesControllerSync instance
        resource_name: Name of the StatefulSet to delete
        namespace: Kubernetes namespace
        pod_label: Label selector for associated pods

    Returns:
        True if cleanup succeeded, False on failure
    """
    console.warn("Recreating PostgreSQL StatefulSet...")
    console.print("[dim]Note: PVCs will be retained to preserve data[/dim]")
    console.print("[dim]Note: Helm release history will be reset[/dim]")

    # Delete the StatefulSet with orphan cascade (keeps PVCs)
    delete_result = controller.delete_resource(
        "statefulset",
        resource_name,
        namespace,
        cascade="orphan",
        wait=True,
    )

    if not delete_result.success:
        console.error(f"Failed to delete StatefulSet:\n{delete_result.stderr}")
        return False

    # Wait for StatefulSet to actually be deleted
    console.info("Waiting for StatefulSet deletion...")
    for _ in range(30):
        if not controller.resource_exists("statefulset", resource_name, namespace):
            break
        time.sleep(1)
    else:
        console.error(
            "Timeout waiting for StatefulSet deletion. "
            "Please delete it manually and retry."
        )
        return False

    console.ok("StatefulSet deleted")

    # Delete orphaned pods (cascade=orphan leaves them running)
    console.info("Deleting orphaned PostgreSQL pods...")
    pod_delete_result = controller.delete_resources_by_label(
        "pod",
        namespace,
        pod_label,
        force=False,
        cascade=None,
    )
    if not pod_delete_result.success:
        console.warn(
            f"Failed to delete pods (may not exist): {pod_delete_result.stderr}"
        )
    else:
        console.ok("Orphaned pods deleted")

    # Clear Helm's cached manifest state (3-way merge prevention)
    console.info("Clearing Helm release metadata...")
    controller.delete_helm_secrets(namespace, "postgresql")
    console.ok("Helm release metadata cleared")

    console.print("[green]✓[/green] Ready for fresh installation (PVCs retained)")
    return True
