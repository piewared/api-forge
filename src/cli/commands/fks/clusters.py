"""FKS cluster management commands: clusters / cluster-create / cluster-destroy."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from src.cli.shared.console import console, with_error_handling
from src.cli.shared.fly import check_prerequisites, get_fly_controller
from src.utils.paths import get_project_root

from . import fks_app
from ._helpers import (
    generate_default_fks_name,
    get_fks_cluster,
    load_fly_fks_settings,
    select_fks_cluster,
)


@fks_app.command(name="clusters")
@with_error_handling
def list_clusters() -> None:
    """List FKS (Fly Kubernetes Service) clusters.

    Shows all Kubernetes clusters in your Fly.io account.

    Examples:
        uv run api-forge-cli fly clusters
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("FKS Clusters")

    clusters = controller.fks_list()

    if not clusters:
        console.info("No FKS clusters found.")
        console.info("Create one with: uv run api-forge-cli fly cluster-create")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Region", style="green")
    table.add_column("Status")
    table.add_column("ID", style="dim")

    for cluster in clusters:
        status = cluster.get("status", "unknown")
        status_color = "green" if status == "running" else "yellow"
        table.add_row(
            cluster.get("name", ""),
            cluster.get("region", ""),
            f"[{status_color}]{status}[/{status_color}]",
            cluster.get("id", ""),
        )

    console.print(table)


@fks_app.command(name="cluster-create")
@with_error_handling
def cluster_create(
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            "-n",
            help="Cluster name (from config if not specified)",
        ),
    ] = None,
    region: Annotated[
        str | None,
        typer.Option(
            "--region",
            "-r",
            help="Fly.io region (from config if not specified)",
        ),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option(
            "--org",
            "-o",
            help="Fly.io organization (from config if not specified)",
        ),
    ] = None,
) -> None:
    """Create a new FKS (Fly Kubernetes Service) cluster.

    Creates a managed Kubernetes cluster on Fly.io's infrastructure.
    After creation, you can deploy using 'fly up'.

    Options not provided will fall back to values from config.yaml.

    Examples:
        # Create using all config defaults
        uv run api-forge-cli fly cluster-create

        # Create with custom name
        uv run api-forge-cli fly cluster-create --name my-cluster

        # Specify region and org
        uv run api-forge-cli fly cluster-create --name my-cluster --region lhr --org my-org
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    # Load settings from config for defaults
    settings = load_fly_fks_settings()

    # Generate deterministic name if not provided
    if not name and not settings.name:
        settings.name = generate_default_fks_name(settings)

    effective_name = name if name else settings.name
    effective_region = region or settings.region
    effective_org = org or settings.org

    console.print_header("Create FKS Cluster")
    console.info(f"Name: {effective_name}")
    console.info(f"Organization: {effective_org}")
    console.info(f"Region: {effective_region}")

    # Check if cluster already exists
    existing = get_fks_cluster(controller, effective_name)
    if existing:
        console.warn(f"Cluster '{effective_name}' already exists.")
        console.info(f"Status: {existing.get('status', 'unknown')}")
        return

    console.info("Creating FKS cluster (this may take a few minutes)...")

    kubeconfig_path = get_project_root() / ".kube" / f"fks-{effective_name}.config"
    kubeconfig_path.parent.mkdir(parents=True, exist_ok=True)

    result = controller.fks_create(
        name=effective_name,
        region=effective_region,
        org=effective_org,
        kubeconfig_output=str(kubeconfig_path),
    )

    if result.success:
        console.ok(f"FKS cluster '{effective_name}' created successfully!")
        console.info(f"Kubeconfig saved to: {kubeconfig_path}")
        console.print_subheader("Next steps")
        console.info(
            f"1. Deploy: uv run api-forge-cli fly up --cluster {effective_name}"
        )
        console.info(f"2. Use kubectl: KUBECONFIG={kubeconfig_path} kubectl get pods")
    else:
        console.error("Failed to create FKS cluster")
        if result.stderr:
            console.info(result.stderr)
        raise typer.Exit(1)


@fks_app.command(name="cluster-destroy")
@with_error_handling
def cluster_destroy(
    cluster: Annotated[
        str | None,
        typer.Option(
            "--cluster",
            "-c",
            help="FKS cluster name",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip confirmation prompt",
        ),
    ] = False,
) -> None:
    """Destroy an FKS cluster.

    WARNING: This permanently destroys the cluster and all workloads.

    Examples:
        uv run api-forge-cli fly cluster-destroy --cluster my-cluster
        uv run api-forge-cli fly cluster-destroy -c my-cluster -y
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("Destroy FKS Cluster")

    cluster_info = select_fks_cluster(controller, cluster)
    cluster_name = cluster_info.get("name", "")

    if not yes:
        if not console.confirm_action(
            f"DESTROY FKS cluster: {cluster_name}",
            "This will:\n"
            "  • Delete all Kubernetes resources\n"
            "  • Remove all persistent volumes\n"
            "  • Destroy the cluster completely",
            extra_warning="This action cannot be undone!",
        ):
            console.info("Operation cancelled")
            raise typer.Exit(0)

    console.info(f"Destroying cluster '{cluster_name}'...")

    result = controller.fks_destroy(cluster_name, confirm=True)

    if result.success:
        console.ok(f"FKS cluster '{cluster_name}' destroyed")

        # Clean up kubeconfig
        kubeconfig_path = get_project_root() / ".kube" / f"fks-{cluster_name}.config"
        if kubeconfig_path.exists():
            kubeconfig_path.unlink()
            console.info(f"Removed kubeconfig: {kubeconfig_path}")
    else:
        console.error("Failed to destroy FKS cluster")
        if result.stderr:
            console.info(result.stderr)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# FKS Deployment Commands
# ---------------------------------------------------------------------------
