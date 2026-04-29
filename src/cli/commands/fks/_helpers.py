"""Shared helpers for FKS commands.

Config loading, deterministic cluster-name generation, cluster lookup /
selection, and kubeconfig persistence. Kept private (underscore prefix
suggested but the leading-underscore module name acts as the package-
private signal here) — only sibling FKS modules consume these.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import md5
from pathlib import Path
from typing import Any

import typer

from src.app.runtime.config.config_loader import update_env_file
from src.cli.shared.config import load_processed_config, load_raw_config
from src.cli.shared.console import console
from src.infra.flyio import FlyCtlControllerSync
from src.utils.paths import get_project_root


@dataclass
class FlyFksSettings:
    """Settings for FKS cluster creation from config.yaml."""

    name: str
    org: str
    region: str


def load_fly_fks_settings() -> FlyFksSettings:
    """Load FKS settings from ``config.yaml``.

    Returns:
        FlyFksSettings populated from ``config.deployments.fly_io``.
    """
    config = load_processed_config()
    fly_io = config.deployments.fly_io
    return FlyFksSettings(
        name=fly_io.fks.name,
        org=fly_io.org,
        region=fly_io.region,
    )


def generate_default_fks_name(settings: FlyFksSettings) -> str:
    """Generate a deterministic FKS cluster name and write it to ``.env``.

    Uses MD5 of the config seed for idempotent naming. (Not security-relevant
    — purely a unique-ish identifier.)

    Args:
        settings: FKS settings.

    Returns:
        Generated cluster name (e.g., ``fks-a1b2c3d4``).
    """
    config = load_raw_config()
    generated_name = f"fks-{md5(str(config['seed']).encode()).hexdigest()[:8]}"
    update_env_file("FLY_FKS_CLUSTER_NAME", generated_name)
    return generated_name


def get_fks_cluster(
    controller: FlyCtlControllerSync,
    cluster: str | None = None,
) -> dict[str, Any] | None:
    """Look up an FKS cluster by name, falling back to the only available one.

    Args:
        controller: Fly.io controller.
        cluster: Cluster name; if omitted and exactly one cluster exists,
            that cluster is returned.

    Returns:
        Cluster info dict, or ``None`` if no match.
    """
    clusters = controller.fks_list()
    if not clusters:
        return None

    if cluster:
        for c in clusters:
            if c.get("name") == cluster or c.get("id") == cluster:
                return c
        return None

    if len(clusters) == 1:
        return clusters[0]

    return None


def select_fks_cluster(
    controller: FlyCtlControllerSync,
    cluster: str | None = None,
) -> dict[str, Any]:
    """Resolve an FKS cluster, prompting interactively if multiple exist.

    Args:
        controller: Fly.io controller.
        cluster: Optional cluster name/id to resolve directly.

    Returns:
        Cluster info dict.

    Raises:
        typer.Exit: If no clusters exist or the named one isn't found.
    """
    clusters = controller.fks_list()
    if not clusters:
        console.error("No FKS clusters found.")
        console.info("Create one with: uv run api-forge-cli fly cluster-create")
        raise typer.Exit(1)

    if cluster:
        for c in clusters:
            if c.get("name") == cluster or c.get("id") == cluster:
                return c
        console.error(f"Cluster not found: {cluster}")
        raise typer.Exit(1)

    if len(clusters) == 1:
        return clusters[0]

    console.print_subheader("Available FKS clusters")
    for i, c in enumerate(clusters, 1):
        status = c.get("status", "unknown")
        console.print(f"  {i}. {c.get('name')} ({c.get('region', 'n/a')}) - {status}")

    try:
        choice = typer.prompt("Select cluster number", type=int)
        if 1 <= choice <= len(clusters):
            return clusters[choice - 1]
    except (ValueError, KeyboardInterrupt):
        pass

    console.error("Invalid selection")
    raise typer.Exit(1)


def ensure_kubeconfig(
    controller: FlyCtlControllerSync,
    cluster_name: str,
    kubeconfig_path: Path | None = None,
) -> Path:
    """Make sure a kubeconfig file is on disk for the given FKS cluster.

    Reuses a pre-existing kubeconfig at the default project location
    (``.kube/fks-<name>.config``); otherwise asks Fly to save one.

    Args:
        controller: Fly.io controller.
        cluster_name: FKS cluster name.
        kubeconfig_path: Override for the kubeconfig destination.

    Returns:
        Path to the kubeconfig file.

    Raises:
        typer.Exit: If saving fails.
    """
    if kubeconfig_path is None:
        kubeconfig_path = get_project_root() / ".kube" / f"fks-{cluster_name}.config"

    kubeconfig_path.parent.mkdir(parents=True, exist_ok=True)

    if kubeconfig_path.exists():
        console.info(f"Using existing kubeconfig: {kubeconfig_path}")
        return kubeconfig_path

    console.info(f"Saving kubeconfig for cluster: {cluster_name}")
    result = controller.fks_save_kubeconfig(cluster_name, output=str(kubeconfig_path))

    if not result.success:
        console.error("Failed to save kubeconfig")
        if result.stderr:
            console.info(result.stderr)
        raise typer.Exit(1)

    console.ok(f"Kubeconfig saved: {kubeconfig_path}")
    return kubeconfig_path
