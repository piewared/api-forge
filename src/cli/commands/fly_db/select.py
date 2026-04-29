"""Fly Postgres cluster selection logic."""

from dataclasses import dataclass

import typer

from src.cli.shared.console import console
from src.infra.flyio import FlyCtlControllerSync

from .settings import _load_fly_db_settings


@dataclass
class SelectedCluster:
    """Information about a selected Fly Postgres cluster."""

    id: str
    name: str
    region: str
    status: str
    plan: str
    is_legacy: bool
    created_at: str | None = None


def _select_cluster(
    controller: FlyCtlControllerSync,
    cluster: str | None,
    *,
    org: str | None = None,
) -> SelectedCluster:
    """Select or find a Fly Postgres cluster (managed or legacy).

    Args:
        controller: Fly.io controller
        cluster: Cluster ID/name (optional, defaults to config.yaml deployments.fly_io.database.name)
        org: Organization filter (optional)

    Returns:
        SelectedCluster with cluster info and whether it's legacy

    Raises:
        typer.Exit: If no cluster found or selection fails
    """
    # If no cluster specified, try to get from config
    if not cluster:
        settings = _load_fly_db_settings()
        if settings.name:
            cluster = settings.name
            console.info(f"Using cluster from config: {cluster}")

    # Collect both managed and legacy clusters
    mpg_clusters = controller.mpg_list(org=org)
    legacy_clusters = controller.postgres_list()

    if cluster:
        # Look up specific cluster - check managed first, then legacy
        mpg_info = controller.mpg_status(cluster)
        if mpg_info:
            return SelectedCluster(
                id=mpg_info.id,
                name=mpg_info.name,
                region=mpg_info.region,
                status=mpg_info.status,
                plan=mpg_info.plan,
                is_legacy=False,
                created_at=mpg_info.created_at,
            )

        # Check legacy clusters by name
        for legacy in legacy_clusters:
            if legacy.name == cluster:
                return SelectedCluster(
                    id=legacy.name,  # Legacy uses app name as ID
                    name=legacy.name,
                    region="",  # Not available from legacy list
                    status=legacy.status,
                    plan="legacy",
                    is_legacy=True,
                )

        console.error(f"Cluster not found: {cluster}")
        raise typer.Exit(1)

    # Build combined list for selection
    all_clusters: list[SelectedCluster] = []

    for c in mpg_clusters:
        all_clusters.append(
            SelectedCluster(
                id=c.id,
                name=c.name,
                region=c.region,
                status=c.status,
                plan=c.plan,
                is_legacy=False,
                created_at=c.created_at,
            )
        )

    for lc in legacy_clusters:
        all_clusters.append(
            SelectedCluster(
                id=lc.name,
                name=lc.name,
                region="",
                status=lc.status,
                plan="legacy",
                is_legacy=True,
            )
        )

    if not all_clusters:
        console.error("No Fly Postgres clusters found.")
        console.info("Create one with: api-forge-cli fly db create managed")
        raise typer.Exit(1)

    if len(all_clusters) == 1:
        return all_clusters[0]

    # Multiple clusters - prompt user to select
    console.print("\n[bold]Available clusters:[/bold]")
    for i, ac in enumerate(all_clusters, 1):
        cluster_type = (
            "[dim](legacy)[/dim]" if ac.is_legacy else "[cyan](managed)[/cyan]"
        )
        console.print(
            f"  {i}. {ac.name} ({ac.region or 'n/a'}) - {ac.status} {cluster_type}"
        )

    try:
        choice = typer.prompt("Select cluster number", type=int)
        if 1 <= choice <= len(all_clusters):
            return all_clusters[choice - 1]
    except (ValueError, KeyboardInterrupt):
        pass

    console.error("Invalid selection")
    raise typer.Exit(1)
