"""FKS deployment commands: up / down / status / history / rollback."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from src.cli.deployment.helm_deployer.deployer import get_deployer
from src.cli.shared.console import console, with_error_handling
from src.cli.shared.fly import check_prerequisites, get_fly_controller

from . import fks_app
from ._helpers import (
    ensure_kubeconfig,
    select_fks_cluster,
)


@fks_app.command()
@with_error_handling
def up(
    cluster: Annotated[
        str | None,
        typer.Option(
            "--cluster",
            "-c",
            help="FKS cluster name",
        ),
    ] = None,
    namespace: Annotated[
        str,
        typer.Option(
            "--namespace",
            "-n",
            help="Kubernetes namespace",
        ),
    ] = "api-forge-prod",
    registry: Annotated[
        str | None,
        typer.Option(
            "--registry",
            "-r",
            help="Container registry URL (e.g., registry.fly.io/myapp)",
        ),
    ] = None,
    app_name: Annotated[
        str | None,
        typer.Option(
            "--app",
            "-a",
            help="Fly app name for LoadBalancer service",
        ),
    ] = None,
    skip_db_check: Annotated[
        bool,
        typer.Option(
            "--skip-db-check",
            help="Skip PostgreSQL verification before deployment",
        ),
    ] = False,
) -> None:
    """Deploy to FKS (Fly Kubernetes Service) cluster using Helm.

    This command:
    - Validates FKS cluster connectivity
    - Builds Docker images with content-based tagging
    - Pushes images to Fly registry (or specified registry)
    - Deploys Kubernetes secrets
    - Syncs config.yaml to Helm values
    - Deploys via Helm upgrade --install
    - FKS automatically provides TLS via LoadBalancer service

    Note: FKS uses LoadBalancer services with automatic TLS instead of Ingress.
    The --ingress flags from k8s are not needed for FKS.

    Examples:
        uv run api-forge-cli fly up --cluster my-cluster
        uv run api-forge-cli fly up -c my-cluster -n my-namespace
        uv run api-forge-cli fly up --cluster my-cluster --app my-fastapi-app
        uv run api-forge-cli fly up --skip-db-check
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("Deploying to FKS")

    # Select cluster
    cluster_info = select_fks_cluster(controller, cluster)
    cluster_name = cluster_info.get("name", "")

    console.info(f"Cluster: {cluster_name}")
    console.info(f"Region: {cluster_info.get('region', 'unknown')}")
    console.info(f"Namespace: {namespace}")

    # Ensure kubeconfig is available
    kubeconfig_path = ensure_kubeconfig(controller, cluster_name)

    # Set KUBECONFIG for helm/kubectl operations
    import os

    original_kubeconfig = os.environ.get("KUBECONFIG")
    os.environ["KUBECONFIG"] = str(kubeconfig_path)

    try:
        # Use existing Helm deployer with FKS-specific settings
        # FKS doesn't need ingress - uses LoadBalancer with Fly's automatic TLS
        deployer = get_deployer()

        # For FKS, we enable a LoadBalancer service instead of Ingress
        # This is handled by Fly's integration
        deployer.deploy(
            namespace=namespace,
            registry=registry,
            # FKS uses LoadBalancer, not Ingress - but we pass these for compatibility
            # The Helm chart should detect FKS and create LoadBalancer service
            ingress_enabled=False,  # Not needed for FKS
            ingress_host=app_name,  # Used as Fly app name if set
            ingress_tls_secret=None,
            ingress_tls_auto=False,  # FKS handles TLS automatically
            ingress_tls_staging=False,
            skip_db_check=skip_db_check,
        )

        console.ok("FKS deployment complete!")

        if app_name:
            console.print_subheader("Your app is available at")
            console.info(f"https://{app_name}.fly.dev")
        else:
            console.info(
                "Run 'uv run api-forge-cli fly status' to see the LoadBalancer URL"
            )

    finally:
        # Restore original KUBECONFIG
        if original_kubeconfig:
            os.environ["KUBECONFIG"] = original_kubeconfig
        else:
            os.environ.pop("KUBECONFIG", None)


@fks_app.command()
@with_error_handling
def down(
    cluster: Annotated[
        str | None,
        typer.Option(
            "--cluster",
            "-c",
            help="FKS cluster name",
        ),
    ] = None,
    namespace: Annotated[
        str,
        typer.Option(
            "--namespace",
            "-n",
            help="Kubernetes namespace",
        ),
    ] = "api-forge-prod",
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip confirmation prompt",
        ),
    ] = False,
) -> None:
    """Remove FKS deployment.

    Uninstalls the Helm release and deletes the namespace.
    This does NOT destroy the FKS cluster itself.

    Examples:
        uv run api-forge-cli fly down --cluster my-cluster
        uv run api-forge-cli fly down -c my-cluster -y
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("Removing FKS Deployment")

    # Select cluster
    cluster_info = select_fks_cluster(controller, cluster)
    cluster_name = cluster_info.get("name", "")

    if not yes:
        if not console.confirm_action(
            "Remove FKS deployment",
            f"This will:\n"
            f"  • Uninstall the Helm release\n"
            f"  • Delete namespace '{namespace}' and all resources\n"
            f"  • Remove all persistent volume claims\n\n"
            f"The FKS cluster '{cluster_name}' itself will NOT be destroyed.",
        ):
            console.info("Operation cancelled")
            raise typer.Exit(0)

    # Ensure kubeconfig
    kubeconfig_path = ensure_kubeconfig(controller, cluster_name)

    import os

    original_kubeconfig = os.environ.get("KUBECONFIG")
    os.environ["KUBECONFIG"] = str(kubeconfig_path)

    try:
        deployer = get_deployer()
        deployer.teardown(namespace=namespace)
    finally:
        if original_kubeconfig:
            os.environ["KUBECONFIG"] = original_kubeconfig
        else:
            os.environ.pop("KUBECONFIG", None)


@fks_app.command()
@with_error_handling
def status(
    cluster: Annotated[
        str | None,
        typer.Option(
            "--cluster",
            "-c",
            help="FKS cluster name",
        ),
    ] = None,
    namespace: Annotated[
        str,
        typer.Option(
            "--namespace",
            "-n",
            help="Kubernetes namespace",
        ),
    ] = "api-forge-prod",
) -> None:
    """Show FKS deployment status.

    Displays the health and configuration of pods, services, and the cluster.

    Examples:
        uv run api-forge-cli fly status --cluster my-cluster
        uv run api-forge-cli fly status -c my-cluster -n my-namespace
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("FKS Deployment Status")

    # Select cluster
    cluster_info = select_fks_cluster(controller, cluster)
    cluster_name = cluster_info.get("name", "")

    # Display cluster info
    console.print_subheader("📦 FKS Cluster")
    table = Table(show_header=False, box=None)
    table.add_column("Key", style="dim")
    table.add_column("Value")
    table.add_row("Name", cluster_name)
    table.add_row("Region", cluster_info.get("region", "unknown"))
    status_val = cluster_info.get("status", "unknown")
    status_color = "green" if status_val == "running" else "yellow"
    table.add_row("Status", f"[{status_color}]{status_val}[/{status_color}]")
    console.print(table)

    # Ensure kubeconfig
    kubeconfig_path = ensure_kubeconfig(controller, cluster_name)

    import os

    original_kubeconfig = os.environ.get("KUBECONFIG")
    os.environ["KUBECONFIG"] = str(kubeconfig_path)

    try:
        deployer = get_deployer()
        console.info(f"Namespace: {namespace}")
        console.print()
        deployer.show_status(namespace=namespace)
    finally:
        if original_kubeconfig:
            os.environ["KUBECONFIG"] = original_kubeconfig
        else:
            os.environ.pop("KUBECONFIG", None)


@fks_app.command()
@with_error_handling
def history(
    cluster: Annotated[
        str | None,
        typer.Option(
            "--cluster",
            "-c",
            help="FKS cluster name",
        ),
    ] = None,
    namespace: Annotated[
        str,
        typer.Option(
            "--namespace",
            "-n",
            help="Kubernetes namespace",
        ),
    ] = "api-forge-prod",
    max_revisions: Annotated[
        int,
        typer.Option(
            "--max",
            "-m",
            help="Maximum number of revisions to show",
        ),
    ] = 10,
) -> None:
    """Show FKS deployment revision history.

    Displays the Helm release history including revision numbers,
    timestamps, status, and descriptions. Use this to identify
    which revision to rollback to.

    Examples:
        uv run api-forge-cli fly history --cluster my-cluster
        uv run api-forge-cli fly history -c my-cluster --max 5
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("FKS Release History")

    cluster_info = select_fks_cluster(controller, cluster)
    cluster_name = cluster_info.get("name", "")

    kubeconfig_path = ensure_kubeconfig(controller, cluster_name)

    import os

    original_kubeconfig = os.environ.get("KUBECONFIG")
    os.environ["KUBECONFIG"] = str(kubeconfig_path)

    try:
        deployer = get_deployer()

        # Get release history
        history_data = deployer.commands.helm.history(
            deployer.constants.HELM_RELEASE_NAME, namespace, max_revisions
        )

        if not history_data:
            console.warn(
                f"No release history found for '{deployer.constants.HELM_RELEASE_NAME}' "
                f"in namespace '{namespace}'"
            )
            console.info("Deploy first with: uv run api-forge-cli fly up")
            return

        table = Table(show_header=True, header_style="bold")
        table.add_column("Revision", justify="right")
        table.add_column("Updated")
        table.add_column("Status")
        table.add_column("Chart")
        table.add_column("Description")

        for entry in history_data:
            revision = entry.get("revision", "")
            updated = entry.get("updated", "")[:19]  # Trim timezone
            status_str = entry.get("status", "")
            chart = entry.get("chart", "")
            description = entry.get("description", "")[:40]

            # Color status
            if status_str == "deployed":
                status_display = f"[green]{status_str}[/green]"
            elif status_str in ("failed", "superseded"):
                status_display = f"[red]{status_str}[/red]"
            elif status_str == "pending-upgrade":
                status_display = f"[yellow]{status_str}[/yellow]"
            else:
                status_display = status_str

            table.add_row(str(revision), updated, status_display, chart, description)

        console.print(table)

        if len(history_data) > 1:
            console.info("To rollback: uv run api-forge-cli fly rollback <revision>")

    finally:
        if original_kubeconfig:
            os.environ["KUBECONFIG"] = original_kubeconfig
        else:
            os.environ.pop("KUBECONFIG", None)


@fks_app.command()
@with_error_handling
def rollback(
    revision: Annotated[
        int | None,
        typer.Argument(
            help="Revision number to rollback to (default: previous revision)",
        ),
    ] = None,
    cluster: Annotated[
        str | None,
        typer.Option(
            "--cluster",
            "-c",
            help="FKS cluster name",
        ),
    ] = None,
    namespace: Annotated[
        str,
        typer.Option(
            "--namespace",
            "-n",
            help="Kubernetes namespace",
        ),
    ] = "api-forge-prod",
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip confirmation prompt",
        ),
    ] = False,
) -> None:
    """Rollback FKS deployment to a previous revision.

    Uses Helm's native rollback functionality to restore
    the deployment to a previous working state.

    Examples:
        uv run api-forge-cli fly rollback --cluster my-cluster
        uv run api-forge-cli fly rollback 3 -c my-cluster
        uv run api-forge-cli fly history -c my-cluster  # View history first
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    console.print_header("FKS Rollback Deployment")

    cluster_info = select_fks_cluster(controller, cluster)
    cluster_name = cluster_info.get("name", "")

    kubeconfig_path = ensure_kubeconfig(controller, cluster_name)

    import os

    original_kubeconfig = os.environ.get("KUBECONFIG")
    os.environ["KUBECONFIG"] = str(kubeconfig_path)

    try:
        deployer = get_deployer()

        # Get release history
        history_data = deployer.commands.helm.history(
            deployer.constants.HELM_RELEASE_NAME, namespace
        )

        if not history_data:
            console.error(
                f"No release history found for '{deployer.constants.HELM_RELEASE_NAME}' "
                f"in namespace '{namespace}'"
            )
            console.info("Make sure the release exists and you have access.")
            raise typer.Exit(1)

        # Show current state
        current = history_data[-1]
        current_revision = int(current.get("revision", 0))

        if current_revision <= 1:
            console.warn("Only one revision exists. Nothing to rollback to.")
            raise typer.Exit(0)

        # Determine target revision
        target_revision = revision if revision is not None else current_revision - 1

        if target_revision < 1 or target_revision >= current_revision:
            console.error(
                f"Invalid revision {target_revision}. "
                f"Must be between 1 and {current_revision - 1}."
            )
            raise typer.Exit(1)

        # Find target revision info
        target_info = next(
            (h for h in history_data if int(h.get("revision", 0)) == target_revision),
            None,
        )

        # Show rollback plan
        console.print_subheader("📋 Rollback Plan")

        table = Table(show_header=True, header_style="bold")
        table.add_column("", style="dim")
        table.add_column("Revision")
        table.add_column("Status")
        table.add_column("Description")

        table.add_row(
            "Current",
            str(current_revision),
            current.get("status", "unknown"),
            current.get("description", "")[:50],
        )

        if target_info:
            table.add_row(
                "Target",
                str(target_revision),
                target_info.get("status", "unknown"),
                target_info.get("description", "")[:50],
            )

        console.print(table)

        # Confirm
        if not yes:
            if not console.confirm_action(
                f"Rollback to revision {target_revision}",
                f"This will restore the deployment in namespace '{namespace}' "
                f"to revision {target_revision}.\n"
                "Active pods will be replaced with the previous configuration.",
            ):
                console.info("Rollback cancelled.")
                raise typer.Exit(0)

        # Perform rollback
        console.print(
            Panel.fit(
                f"[bold yellow]⏪ Rolling back to revision {target_revision}[/bold yellow]",
                border_style="yellow",
            )
        )

        result = deployer.commands.helm.rollback(
            deployer.constants.HELM_RELEASE_NAME,
            namespace,
            target_revision,
            wait=True,
            timeout="5m",
        )

        if result.success:
            console.ok(f"Successfully rolled back to revision {target_revision}!")
            console.info("Run 'uv run api-forge-cli fly status' to verify.")
        else:
            console.error("Rollback failed")
            if result.stderr:
                console.print(Panel(result.stderr, title="Error", border_style="red"))
            raise typer.Exit(1)

    finally:
        if original_kubeconfig:
            os.environ["KUBECONFIG"] = original_kubeconfig
        else:
            os.environ.pop("KUBECONFIG", None)
