"""Kubernetes Helm deployment commands.

This module provides commands for deploying, managing, and monitoring
Kubernetes deployments via Helm.
"""

from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from src.cli.context import get_cli_context
from src.cli.deployment.helm_deployer.deployer import get_deployer
from src.cli.shared.console import console, with_error_handling

from .k8s_db import k8s_db_app
from .k8s_tls import check_cluster_issuer_ready, k8s_tls_app

# ---------------------------------------------------------------------------
# Typer App
# ---------------------------------------------------------------------------

k8s_app = typer.Typer(
    name="k8s",
    help="Kubernetes Helm deployment commands.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@k8s_app.command()
@with_error_handling
def up(
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
            help="Container registry URL (e.g., ghcr.io/myuser)",
        ),
    ] = None,
    ingress: Annotated[
        bool,
        typer.Option(
            "--ingress",
            help="Enable Ingress for external access",
        ),
    ] = False,
    ingress_host: Annotated[
        str | None,
        typer.Option(
            "--ingress-host",
            help="Hostname for Ingress (e.g., api.example.com)",
        ),
    ] = None,
    ingress_tls_secret: Annotated[
        str | None,
        typer.Option(
            "--ingress-tls-secret",
            help="TLS secret name for HTTPS (manual certificate)",
        ),
    ] = None,
    ingress_tls_auto: Annotated[
        bool,
        typer.Option(
            "--ingress-tls-auto",
            help="Auto-provision TLS via cert-manager (requires setup-tls first)",
        ),
    ] = False,
    ingress_tls_staging: Annotated[
        bool,
        typer.Option(
            "--ingress-tls-staging",
            help="Use Let's Encrypt staging (with --ingress-tls-auto)",
        ),
    ] = False,
    skip_db_check: Annotated[
        bool,
        typer.Option(
            "--skip-db-check",
            help="Skip PostgreSQL verification before deployment",
        ),
    ] = False,
) -> None:
    """Deploy to Kubernetes cluster using Helm.

    This command:
    - Runs pre-deployment validation with cleanup prompts
    - Builds Docker images with content-based tagging
    - Loads images into target cluster (Minikube, Kind, or registry)
    - Deploys Kubernetes secrets
    - Restarts postgres StatefulSet (if bundled postgres enabled)
    - Verifies PostgreSQL is accessible (unless --skip-db-check)
    - Syncs config.yaml to Helm values
    - Deploys via Helm upgrade --install
    - Waits for rollouts to complete

    Examples:
        uv run api-forge-cli k8s up
        uv run api-forge-cli k8s up -n my-namespace
        uv run api-forge-cli k8s up --registry ghcr.io/myuser
        uv run api-forge-cli k8s up --ingress --ingress-host api.example.com
        uv run api-forge-cli k8s up --ingress --ingress-host api.example.com --ingress-tls-auto
        uv run api-forge-cli k8s up --skip-db-check   # Skip database verification
    """
    console.print_header("Deploying to Kubernetes")

    # Validate TLS options
    if ingress_tls_auto and ingress_tls_secret:
        console.print(
            "[red]Cannot use both --ingress-tls-auto and --ingress-tls-secret[/red]"
        )
        raise typer.Exit(1)

    if ingress_tls_auto and not ingress:
        console.info("--ingress-tls-auto implies --ingress, enabling it")
        ingress = True

    if ingress_tls_staging and not ingress_tls_auto:
        console.error("--ingress-tls-staging requires --ingress-tls-auto")
        raise typer.Exit(1)

    # Check cert-manager is ready if using auto TLS
    if ingress_tls_auto:
        issuer_name = (
            "letsencrypt-staging" if ingress_tls_staging else "letsencrypt-prod"
        )
        if not check_cluster_issuer_ready(issuer_name):
            console.print(
                f"[red]ClusterIssuer '{issuer_name}' not found or not ready.[/red]"
            )
            console.print("\n[dim]Run setup-tls first:[/dim]")
            staging_flag = " --staging" if ingress_tls_staging else ""
            console.print(
                f"  [cyan]uv run api-forge-cli k8s tls setup --email your@email.com{staging_flag}[/cyan]"
            )
            raise typer.Exit(1)
    deployer = get_deployer()
    deployer.deploy(
        namespace=namespace,
        registry=registry,
        ingress_enabled=ingress,
        ingress_host=ingress_host,
        ingress_tls_secret=ingress_tls_secret,
        ingress_tls_auto=ingress_tls_auto,
        ingress_tls_staging=ingress_tls_staging,
        skip_db_check=skip_db_check,
    )


@k8s_app.command()
@with_error_handling
def down(
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
    """Remove Kubernetes deployment.

    Uninstalls the Helm release and deletes the namespace.

    Examples:
        uv run api-forge-cli k8s down
        uv run api-forge-cli k8s down -n my-namespace
        uv run api-forge-cli k8s down -y  # Skip confirmation
    """
    console.print_header("Removing Kubernetes Deployment")

    if not yes:
        if not console.confirm_action(
            "Remove Kubernetes deployment",
            f"This will:\n"
            f"  • Uninstall the Helm release\n"
            f"  • Delete namespace '{namespace}' and all resources\n"
            f"  • Remove all persistent volume claims",
        ):
            console.print("[dim]Operation cancelled[/dim]")
            raise typer.Exit(0)

    deployer = get_deployer()
    deployer.teardown(namespace=namespace)


@k8s_app.command()
@with_error_handling
def status(
    namespace: Annotated[
        str,
        typer.Option(
            "--namespace",
            "-n",
            help="Kubernetes namespace",
        ),
    ] = "api-forge-prod",
) -> None:
    """Show the status of Kubernetes deployment.

    Displays the health and configuration of pods, services, and ingress.

    Examples:
        uv run api-forge-cli k8s status
        uv run api-forge-cli k8s status -n my-namespace
    """
    console.print_header("Kubernetes Deployment Status")

    deployer = get_deployer()
    deployer.show_status(namespace=namespace)


@k8s_app.command()
@with_error_handling
def history(
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
    """Show Kubernetes deployment revision history.

    Displays the Helm release history including revision numbers,
    timestamps, status, and descriptions. Use this to identify
    which revision to rollback to.

    Examples:
        uv run api-forge-cli k8s history
        uv run api-forge-cli k8s history --max 5
    """
    console.print_header("Release History")

    deployer = get_deployer()

    # Get release history
    history_data = deployer.commands.helm.history(
        deployer.constants.HELM_RELEASE_NAME, namespace, max_revisions
    )

    if not history_data:
        console.print(
            f"[yellow]No release history found for '{deployer.constants.HELM_RELEASE_NAME}' "
            f"in namespace '{namespace}'[/yellow]"
        )
        console.print("\n[dim]Deploy first with: uv run api-forge-cli k8s up[/dim]")
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

    # Show rollback hint
    if len(history_data) > 1:
        console.print(
            "\n[dim]To rollback: uv run api-forge-cli k8s rollback <revision>[/dim]"
        )


@k8s_app.command()
@with_error_handling
def rollback(
    revision: Annotated[
        int | None,
        typer.Argument(
            help="Revision number to rollback to (default: previous revision)",
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
    """Rollback Kubernetes deployment to a previous revision.

    Uses Helm's native rollback functionality to restore
    the deployment to a previous working state.

    Examples:
        uv run api-forge-cli k8s rollback          # Previous revision
        uv run api-forge-cli k8s rollback 3        # Specific revision
        uv run api-forge-cli k8s history           # View history first
    """
    console.print_header("Rollback Deployment")

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
        console.print("\n[dim]Make sure the release exists and you have access.[/dim]")
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
        (h for h in history_data if int(h.get("revision", 0)) == target_revision), None
    )

    # Show rollback plan
    console.print("\n[bold cyan]📋 Rollback Plan[/bold cyan]\n")

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
            console.print("[dim]Rollback cancelled.[/dim]")
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
        console.ok(f"\nSuccessfully rolled back to revision {target_revision}!")
        console.print("\n[dim]Run 'uv run api-forge-cli k8s status' to verify.[/dim]")
    else:
        console.error("\nRollback failed")
        if result.stderr:
            console.print(Panel(result.stderr, title="Error", border_style="red"))
        raise typer.Exit(1)


@k8s_app.command()
@with_error_handling
def logs(
    pod: Annotated[
        str | None,
        typer.Argument(
            help="Pod name or label selector (e.g., 'app=api-forge')",
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
    container: Annotated[
        str | None,
        typer.Option(
            "--container",
            "-c",
            help="Container name (if pod has multiple containers)",
        ),
    ] = None,
    follow: Annotated[
        bool,
        typer.Option(
            "--follow",
            "-f",
            help="Follow log output",
        ),
    ] = False,
    tail: Annotated[
        int,
        typer.Option(
            "--tail",
            help="Number of lines to show from the end of the logs",
        ),
    ] = 100,
    previous: Annotated[
        bool,
        typer.Option(
            "--previous",
            "-p",
            help="Show logs from previous container instance",
        ),
    ] = False,
) -> None:
    """View logs from Kubernetes pods.

    Shows logs from pods in the deployment. If no pod is specified,
    shows logs from all pods with the app label.

    Examples:
        uv run api-forge-cli k8s logs                    # All app pods
        uv run api-forge-cli k8s logs api-forge-abc123   # Specific pod
        uv run api-forge-cli k8s logs -f                 # Follow logs
        uv run api-forge-cli k8s logs --previous         # Previous container
    """
    console.print(f"[dim]Namespace: {namespace}[/dim]\n")

    # Determine label selector for non-specific pod requests
    label_selector = "app=api-forge" if not pod else None

    try:
        controller = get_cli_context().k8s_controller
        result = controller.get_pod_logs(
            namespace=namespace,
            pod=pod,
            container=container,
            label_selector=label_selector,
            follow=follow,
            tail=tail,
            previous=previous,
        )

        if result.stdout:
            console.print(result.stdout)
        if not result.success and result.stderr:
            console.print(f"[red]{result.stderr}[/red]")
    except KeyboardInterrupt:
        console.print("\n[dim]Log streaming stopped[/dim]")


# ---------------------------------------------------------------------------
# Register Subcommands
# ---------------------------------------------------------------------------

k8s_app.add_typer(k8s_db_app, name="db")
k8s_app.add_typer(k8s_tls_app, name="tls")
