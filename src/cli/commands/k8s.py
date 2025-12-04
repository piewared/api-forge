"""Kubernetes Helm deployment commands.

This module provides commands for deploying, managing, and monitoring
Kubernetes deployments via Helm.
"""

from typing import TYPE_CHECKING, Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from .shared import (
    confirm_action,
    console,
    get_project_root,
    handle_error,
    print_header,
    with_error_handling,
)

if TYPE_CHECKING:
    from src.cli.deployment.helm_deployer.deployer import HelmDeployer


# ---------------------------------------------------------------------------
# Deployer Factory
# ---------------------------------------------------------------------------


def _get_deployer() -> "HelmDeployer":
    """Get the Helm deployer instance.

    Returns:
        HelmDeployer instance configured for current project
    """
    from src.cli.deployment.helm_deployer.deployer import HelmDeployer

    return HelmDeployer(console, get_project_root())


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
            help="TLS secret name for HTTPS",
        ),
    ] = None,
) -> None:
    """Deploy to Kubernetes cluster using Helm.

    This command:
    - Runs pre-deployment validation with cleanup prompts
    - Builds Docker images with content-based tagging
    - Loads images into target cluster (Minikube, Kind, or registry)
    - Deploys Kubernetes secrets
    - Syncs config.yaml to Helm values
    - Deploys via Helm upgrade --install
    - Waits for rollouts to complete

    Examples:
        uv run api-forge-cli k8s up
        uv run api-forge-cli k8s up -n my-namespace
        uv run api-forge-cli k8s up --registry ghcr.io/myuser
        uv run api-forge-cli k8s up --ingress --ingress-host api.example.com
    """
    print_header("Deploying to Kubernetes")

    deployer = _get_deployer()
    deployer.deploy(
        namespace=namespace,
        registry=registry,
        ingress_enabled=ingress,
        ingress_host=ingress_host,
        ingress_tls_secret=ingress_tls_secret,
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
    print_header("Removing Kubernetes Deployment")

    if not yes:
        if not confirm_action(
            "Remove Kubernetes deployment",
            f"This will:\n"
            f"  • Uninstall the Helm release\n"
            f"  • Delete namespace '{namespace}' and all resources\n"
            f"  • Remove all persistent volume claims",
        ):
            console.print("[dim]Operation cancelled[/dim]")
            raise typer.Exit(0)

    deployer = _get_deployer()
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
    print_header("Kubernetes Deployment Status")

    deployer = _get_deployer()
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
    print_header("Release History")

    deployer = _get_deployer()

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
    print_header("Rollback Deployment")

    deployer = _get_deployer()

    # Get release history
    history_data = deployer.commands.helm.history(
        deployer.constants.HELM_RELEASE_NAME, namespace
    )

    if not history_data:
        console.print(
            f"[red]No release history found for '{deployer.constants.HELM_RELEASE_NAME}' "
            f"in namespace '{namespace}'[/red]"
        )
        console.print("\n[dim]Make sure the release exists and you have access.[/dim]")
        raise typer.Exit(1)

    # Show current state
    current = history_data[-1]
    current_revision = int(current.get("revision", 0))

    if current_revision <= 1:
        console.print(
            "[yellow]⚠ Only one revision exists. Nothing to rollback to.[/yellow]"
        )
        raise typer.Exit(0)

    # Determine target revision
    target_revision = revision if revision is not None else current_revision - 1

    if target_revision < 1 or target_revision >= current_revision:
        console.print(
            f"[red]Invalid revision {target_revision}. "
            f"Must be between 1 and {current_revision - 1}.[/red]"
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
        if not confirm_action(
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
        console.print(
            f"\n[bold green]✅ Successfully rolled back to revision {target_revision}![/bold green]"
        )
        console.print("\n[dim]Run 'uv run api-forge-cli k8s status' to verify.[/dim]")
    else:
        console.print("\n[bold red]❌ Rollback failed[/bold red]")
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
    import subprocess

    # Build kubectl logs command
    cmd = ["kubectl", "logs", "-n", namespace]

    if pod:
        cmd.append(pod)
    else:
        # Use label selector to get all app pods
        cmd.extend(["-l", "app=api-forge", "--all-containers=true"])

    if container:
        cmd.extend(["-c", container])

    if follow:
        cmd.append("-f")

    cmd.extend([f"--tail={tail}"])

    if previous:
        cmd.append("--previous")

    console.print(f"[dim]Namespace: {namespace}[/dim]\n")

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        handle_error(f"Failed to retrieve logs: {e}")
        raise typer.Exit(1) from e
    except KeyboardInterrupt:
        console.print("\n[dim]Log streaming stopped[/dim]")


@k8s_app.command(name="setup-tls")
@with_error_handling
def setup_tls(
    namespace: Annotated[
        str,
        typer.Option(
            "--namespace",
            "-n",
            help="Kubernetes namespace",
        ),
    ] = "api-forge-prod",
    email: Annotated[
        str | None,
        typer.Option(
            "--email",
            "-e",
            help="Email for Let's Encrypt certificate notifications",
        ),
    ] = None,
    staging: Annotated[
        bool,
        typer.Option(
            "--staging",
            help="Use Let's Encrypt staging server (for testing)",
        ),
    ] = False,
) -> None:
    """Set up TLS with cert-manager and Let's Encrypt.

    Creates a ClusterIssuer for automatic TLS certificate provisioning.
    Requires cert-manager to be installed in the cluster.

    Examples:
        uv run api-forge-cli k8s setup-tls --email admin@example.com
        uv run api-forge-cli k8s setup-tls --email admin@example.com --staging
    """
    import subprocess

    print_header("TLS Setup with cert-manager")

    if not email:
        console.print("[red]Email is required for Let's Encrypt registration.[/red]")
        console.print(
            "[dim]Use: uv run api-forge-cli k8s setup-tls --email admin@example.com[/dim]"
        )
        raise typer.Exit(1)

    # Check if cert-manager is installed
    console.print("[cyan]Checking cert-manager installation...[/cyan]")
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", "cert-manager", "-o", "name"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 or not result.stdout.strip():
        console.print("[red]cert-manager is not installed.[/red]")
        console.print("\n[dim]Install cert-manager first:[/dim]")
        console.print(
            "  kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.0/cert-manager.yaml"
        )
        raise typer.Exit(1)

    console.print("[green]✓[/green] cert-manager is installed")

    # Determine which server to use
    if staging:
        server = "https://acme-staging-v02.api.letsencrypt.org/directory"
        issuer_name = "letsencrypt-staging"
        console.print(
            "[yellow]Using Let's Encrypt staging server (for testing)[/yellow]"
        )
    else:
        server = "https://acme-v02.api.letsencrypt.org/directory"
        issuer_name = "letsencrypt-prod"
        console.print("[cyan]Using Let's Encrypt production server[/cyan]")

    # Create ClusterIssuer manifest
    cluster_issuer_yaml = f"""apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: {issuer_name}
spec:
  acme:
    server: {server}
    email: {email}
    privateKeySecretRef:
      name: {issuer_name}-account-key
    solvers:
    - http01:
        ingress:
          class: nginx
"""

    console.print(f"\n[cyan]Creating ClusterIssuer '{issuer_name}'...[/cyan]")

    # Apply the manifest
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=cluster_issuer_yaml,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        console.print("[red]Failed to create ClusterIssuer[/red]")
        if result.stderr:
            console.print(Panel(result.stderr, title="Error", border_style="red"))
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] ClusterIssuer '{issuer_name}' created")

    # Show next steps
    console.print("\n[bold cyan]Next Steps:[/bold cyan]")
    console.print("  1. Deploy with Ingress enabled:")
    console.print(
        "     [dim]uv run api-forge-cli k8s up --ingress --ingress-host api.example.com[/dim]"
    )
    console.print("  2. Add the annotation to your Ingress:")
    console.print(f"     [dim]cert-manager.io/cluster-issuer: {issuer_name}[/dim]")
    console.print("  3. cert-manager will automatically provision a certificate")

    if staging:
        console.print(
            "\n[yellow]Note: Staging certificates are not trusted by browsers.[/yellow]"
        )
        console.print(
            "[yellow]Use --no-staging for production once testing is complete.[/yellow]"
        )
