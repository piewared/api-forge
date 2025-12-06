"""Kubernetes Helm deployment commands.

This module provides commands for deploying, managing, and monitoring
Kubernetes deployments via Helm.
"""

from typing import TYPE_CHECKING, Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from src.infra.k8s import KubectlController, run_sync

from .shared import (
    confirm_action,
    console,
    get_project_root,
    print_header,
    with_error_handling,
)

if TYPE_CHECKING:
    from src.cli.deployment.helm_deployer.deployer import HelmDeployer


# ---------------------------------------------------------------------------
# Kubernetes Controller (module-level singleton)
# ---------------------------------------------------------------------------

_controller = KubectlController()


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
# Helper Functions
# ---------------------------------------------------------------------------


def _check_cluster_issuer_ready(issuer_name: str) -> bool:
    """Check if a ClusterIssuer exists and is ready.

    Args:
        issuer_name: Name of the ClusterIssuer to check

    Returns:
        True if the ClusterIssuer exists and is ready, False otherwise
    """
    status = run_sync(_controller.get_cluster_issuer_status(issuer_name))
    return status.exists and status.ready


def _check_cert_manager_installed() -> bool:
    """Check if cert-manager is installed in the cluster.

    Returns:
        True if cert-manager pods are running, False otherwise
    """
    return run_sync(_controller.check_cert_manager_installed())


def _install_cert_manager() -> bool:
    """Install cert-manager using Helm.

    Returns:
        True if installation succeeded, False otherwise
    """
    import subprocess

    console.print("[cyan]Installing cert-manager via Helm...[/cyan]")

    # Add Helm repo
    subprocess.run(
        ["helm", "repo", "add", "jetstack", "https://charts.jetstack.io"],
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["helm", "repo", "update"],
        capture_output=True,
        check=False,
    )

    # Install cert-manager
    result = subprocess.run(
        [
            "helm",
            "install",
            "cert-manager",
            "jetstack/cert-manager",
            "--namespace",
            "cert-manager",
            "--create-namespace",
            "--set",
            "installCRDs=true",
            "--wait",
            "--timeout",
            "5m",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        console.print("[red]Failed to install cert-manager[/red]")
        if result.stderr:
            console.print(f"[dim]{result.stderr}[/dim]")
        return False

    console.print("[green]✓[/green] cert-manager installed successfully")
    return True


def _wait_for_cluster_issuer(issuer_name: str, timeout: int = 60) -> bool:
    """Wait for a ClusterIssuer to become ready.

    Args:
        issuer_name: Name of the ClusterIssuer
        timeout: Maximum seconds to wait

    Returns:
        True if issuer became ready, False if timeout
    """
    import time

    console.print(
        f"[dim]Waiting for ClusterIssuer '{issuer_name}' to be ready...[/dim]"
    )

    start = time.time()
    while time.time() - start < timeout:
        if _check_cluster_issuer_ready(issuer_name):
            return True
        time.sleep(2)

    # Check if it exists but isn't ready
    yaml_output = run_sync(_controller.get_cluster_issuer_yaml(issuer_name))
    if yaml_output:
        console.print("[yellow]ClusterIssuer exists but not ready yet[/yellow]")
        console.print(f"[dim]{yaml_output}[/dim]")

    return False


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
        uv run api-forge-cli k8s up --ingress --ingress-host api.example.com --ingress-tls-auto
    """
    print_header("Deploying to Kubernetes")

    # Validate TLS options
    if ingress_tls_auto and ingress_tls_secret:
        console.print(
            "[red]Cannot use both --ingress-tls-auto and --ingress-tls-secret[/red]"
        )
        raise typer.Exit(1)

    if ingress_tls_auto and not ingress:
        console.print(
            "[yellow]--ingress-tls-auto implies --ingress, enabling it[/yellow]"
        )
        ingress = True

    if ingress_tls_staging and not ingress_tls_auto:
        console.print("[red]--ingress-tls-staging requires --ingress-tls-auto[/red]")
        raise typer.Exit(1)

    # Check cert-manager is ready if using auto TLS
    if ingress_tls_auto:
        issuer_name = (
            "letsencrypt-staging" if ingress_tls_staging else "letsencrypt-prod"
        )
        if not _check_cluster_issuer_ready(issuer_name):
            console.print(
                f"[red]ClusterIssuer '{issuer_name}' not found or not ready.[/red]"
            )
            console.print("\n[dim]Run setup-tls first:[/dim]")
            staging_flag = " --staging" if ingress_tls_staging else ""
            console.print(
                f"  [cyan]uv run api-forge-cli k8s setup-tls --email your@email.com{staging_flag}[/cyan]"
            )
            raise typer.Exit(1)

    deployer = _get_deployer()
    deployer.deploy(
        namespace=namespace,
        registry=registry,
        ingress_enabled=ingress,
        ingress_host=ingress_host,
        ingress_tls_secret=ingress_tls_secret,
        ingress_tls_auto=ingress_tls_auto,
        ingress_tls_staging=ingress_tls_staging,
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
    console.print(f"[dim]Namespace: {namespace}[/dim]\n")

    # Determine label selector for non-specific pod requests
    label_selector = "app=api-forge" if not pod else None

    try:
        result = run_sync(
            _controller.get_pod_logs(
                namespace=namespace,
                pod=pod,
                container=container,
                label_selector=label_selector,
                follow=follow,
                tail=tail,
                previous=previous,
            )
        )
        if result.stdout:
            console.print(result.stdout)
        if not result.success and result.stderr:
            console.print(f"[red]{result.stderr}[/red]")
    except KeyboardInterrupt:
        console.print("\n[dim]Log streaming stopped[/dim]")


@k8s_app.command(name="setup-tls")
@with_error_handling
def setup_tls(
    email: Annotated[
        str | None,
        typer.Option(
            "--email",
            "-e",
            help="Email for Let's Encrypt certificate notifications (required)",
        ),
    ] = None,
    staging: Annotated[
        bool,
        typer.Option(
            "--staging",
            help="Use Let's Encrypt staging server (for testing)",
        ),
    ] = False,
    install_cert_manager: Annotated[
        bool,
        typer.Option(
            "--install-cert-manager",
            help="Automatically install cert-manager if not present",
        ),
    ] = True,
) -> None:
    """Set up TLS with cert-manager and Let's Encrypt.

    This command:
    1. Checks if cert-manager is installed (installs via Helm if not)
    2. Creates a ClusterIssuer for Let's Encrypt
    3. Waits for the ClusterIssuer to be ready

    After setup, use --ingress-tls-auto with 'k8s up' for automatic certificates.

    Examples:
        uv run api-forge-cli k8s setup-tls --email admin@example.com
        uv run api-forge-cli k8s setup-tls --email admin@example.com --staging
        uv run api-forge-cli k8s up --ingress --ingress-host api.example.com --ingress-tls-auto
    """
    print_header("TLS Setup with cert-manager")

    if not email:
        console.print("[red]Email is required for Let's Encrypt registration.[/red]")
        console.print("\n[dim]Example:[/dim]")
        console.print(
            "  [cyan]uv run api-forge-cli k8s setup-tls --email admin@example.com[/cyan]"
        )
        raise typer.Exit(1)

    # Step 1: Check/install cert-manager
    console.print("\n[bold]Step 1/3:[/bold] Checking cert-manager installation...")

    if _check_cert_manager_installed():
        console.print("[green]✓[/green] cert-manager is already installed")
    else:
        if install_cert_manager:
            console.print("[yellow]cert-manager not found, installing...[/yellow]")
            if not _install_cert_manager():
                raise typer.Exit(1)
        else:
            console.print("[red]cert-manager is not installed.[/red]")
            console.print(
                "\n[dim]Run with --install-cert-manager or install manually:[/dim]"
            )
            console.print(
                "  helm install cert-manager jetstack/cert-manager "
                "--namespace cert-manager --create-namespace --set installCRDs=true"
            )
            raise typer.Exit(1)

    # Step 2: Create ClusterIssuer
    console.print("\n[bold]Step 2/3:[/bold] Creating ClusterIssuer...")

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

    # Check if issuer already exists and is ready
    if _check_cluster_issuer_ready(issuer_name):
        console.print(
            f"[green]✓[/green] ClusterIssuer '{issuer_name}' already exists and is ready"
        )
    else:
        # Create ClusterIssuer manifest file (version-controlled, GitOps-friendly)
        project_root = get_project_root()
        cert_manager_dir = project_root / "infra" / "helm" / "cert-manager"
        cert_manager_dir.mkdir(parents=True, exist_ok=True)

        issuer_file = cert_manager_dir / f"{issuer_name}.yaml"

        cluster_issuer_yaml = f"""# ClusterIssuer for Let's Encrypt TLS certificates
# Generated by: uv run api-forge-cli k8s setup-tls --email {email}
# This is a cluster-scoped resource (not namespaced).
# Apply with: kubectl apply -f {issuer_file.relative_to(project_root)}
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: {issuer_name}
  labels:
    app.kubernetes.io/managed-by: api-forge-cli
spec:
  acme:
    # Let's Encrypt ACME server
    server: {server}
    # Email for certificate expiration notifications
    email: {email}
    # Secret to store the ACME account private key
    privateKeySecretRef:
      name: {issuer_name}-account-key
    # HTTP-01 challenge solver using NGINX ingress
    solvers:
    - http01:
        ingress:
          class: nginx
"""

        # Write manifest to file
        issuer_file.write_text(cluster_issuer_yaml)
        console.print(
            f"[dim]Wrote ClusterIssuer manifest to {issuer_file.relative_to(project_root)}[/dim]"
        )

        # Apply the manifest
        console.print(f"[dim]Applying ClusterIssuer '{issuer_name}'...[/dim]")

        result = run_sync(_controller.apply_manifest(issuer_file))

        if not result.success:
            console.print("[red]Failed to create ClusterIssuer[/red]")
            if result.stderr:
                console.print(Panel(result.stderr, title="Error", border_style="red"))
            raise typer.Exit(1)

        console.print(f"[green]✓[/green] ClusterIssuer '{issuer_name}' created")

    # Step 3: Wait for ClusterIssuer to be ready
    console.print("\n[bold]Step 3/3:[/bold] Waiting for ClusterIssuer to be ready...")

    if _wait_for_cluster_issuer(issuer_name, timeout=60):
        console.print(f"[green]✓[/green] ClusterIssuer '{issuer_name}' is ready")
    else:
        console.print(
            f"[yellow]⚠ ClusterIssuer '{issuer_name}' created but not ready yet[/yellow]"
        )
        console.print(
            "[dim]This is normal - it will become ready when you create your first certificate.[/dim]"
        )

    # Success message with next steps
    console.print("\n" + "=" * 60)
    console.print("[bold green]✅ TLS setup complete![/bold green]")
    console.print("=" * 60)

    console.print("\n[bold cyan]Deploy with automatic TLS:[/bold cyan]")
    staging_flag = " --ingress-tls-staging" if staging else ""
    console.print(
        f"  [cyan]uv run api-forge-cli k8s up --ingress --ingress-host api.example.com --ingress-tls-auto{staging_flag}[/cyan]"
    )

    console.print("\n[bold cyan]What happens next:[/bold cyan]")
    console.print("  1. Ingress is created with cert-manager annotation")
    console.print("  2. cert-manager detects the annotation and requests a certificate")
    console.print("  3. Let's Encrypt validates domain ownership via HTTP-01 challenge")
    console.print("  4. Certificate is stored in a Kubernetes secret")
    console.print("  5. NGINX Ingress serves HTTPS automatically")
    console.print("  6. cert-manager auto-renews before expiry")

    if staging:
        console.print(
            "\n[yellow]⚠ Staging certificates are not trusted by browsers.[/yellow]"
        )
        console.print(
            "[yellow]  Run without --staging for production certificates.[/yellow]"
        )

    console.print("\n[bold cyan]Manifest saved to:[/bold cyan]")
    console.print(f"  [dim]infra/helm/cert-manager/{issuer_name}.yaml[/dim]")
    console.print(
        "  [dim]Commit this file to version control for GitOps workflows.[/dim]"
    )
