"""Kubernetes TLS setup with cert-manager and Let's Encrypt.

Provides the setup-tls command for installing cert-manager and creating
ClusterIssuers for automatic TLS certificate provisioning.
"""

import time
from typing import Annotated

import typer
from rich.panel import Panel

from src.cli.context import get_cli_context
from src.cli.shared.console import console, with_error_handling
from src.utils.paths import get_project_root

# ---------------------------------------------------------------------------
# Typer App
# ---------------------------------------------------------------------------

k8s_tls_app = typer.Typer(
    name="tls",
    help="TLS certificate management for Kubernetes.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def check_cluster_issuer_ready(issuer_name: str) -> bool:
    """Check if a ClusterIssuer exists and is ready.

    Args:
        issuer_name: Name of the ClusterIssuer to check

    Returns:
        True if the ClusterIssuer exists and is ready, False otherwise
    """
    controller = get_cli_context().k8s_controller
    status = controller.get_cluster_issuer_status(issuer_name)
    return bool(status.exists and status.ready)


def _check_cert_manager_installed() -> bool:
    """Check if cert-manager is installed in the cluster.

    Returns:
        True if cert-manager pods are running, False otherwise
    """
    controller = get_cli_context().k8s_controller
    result: bool = controller.check_cert_manager_installed()
    return result


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
    console.print(
        f"[dim]Waiting for ClusterIssuer '{issuer_name}' to be ready...[/dim]"
    )

    start = time.time()
    while time.time() - start < timeout:
        if check_cluster_issuer_ready(issuer_name):
            return True
        time.sleep(2)

    # Check if it exists but isn't ready
    controller = get_cli_context().k8s_controller
    yaml_output = controller.get_cluster_issuer_yaml(issuer_name)
    if yaml_output:
        console.print("[yellow]ClusterIssuer exists but not ready yet[/yellow]")
        console.print(f"[dim]{yaml_output}[/dim]")

    return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@k8s_tls_app.command(name="setup")
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
        uv run api-forge-cli k8s tls setup --email admin@example.com
        uv run api-forge-cli k8s tls setup --email admin@example.com --staging
        uv run api-forge-cli k8s up --ingress --ingress-host api.example.com --ingress-tls-auto
    """
    console.print_header("TLS Setup with cert-manager")

    if not email:
        console.print("[red]Email is required for Let's Encrypt registration.[/red]")
        console.print("\n[dim]Example:[/dim]")
        console.print(
            "  [cyan]uv run api-forge-cli k8s tls setup --email admin@example.com[/cyan]"
        )
        raise typer.Exit(1)

    # Step 1: Check/install cert-manager
    console.print("\n[bold]Step 1/3:[/bold] Checking cert-manager installation...")

    if _check_cert_manager_installed():
        console.ok("cert-manager is already installed")
    else:
        if install_cert_manager:
            console.info("cert-manager not found, installing...")
            if not _install_cert_manager():
                raise typer.Exit(1)
        else:
            console.error("cert-manager is not installed.")
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
        console.info("Using Let's Encrypt staging server (for testing)")
    else:
        server = "https://acme-v02.api.letsencrypt.org/directory"
        issuer_name = "letsencrypt-prod"
        console.info("Using Let's Encrypt production server")

    # Check if issuer already exists and is ready
    if check_cluster_issuer_ready(issuer_name):
        console.ok(f"ClusterIssuer '{issuer_name}' already exists and is ready")
    else:
        # Create ClusterIssuer manifest file (version-controlled, GitOps-friendly)
        project_root = get_project_root()
        cert_manager_dir = project_root / "infra" / "helm" / "cert-manager"
        cert_manager_dir.mkdir(parents=True, exist_ok=True)

        issuer_file = cert_manager_dir / f"{issuer_name}.yaml"

        cluster_issuer_yaml = f"""# ClusterIssuer for Let's Encrypt TLS certificates
# Generated by: uv run api-forge-cli k8s tls setup --email {email}
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

        controller = get_cli_context().k8s_controller
        result = controller.apply_manifest(issuer_file)

        if not result.success:
            console.error("Failed to create ClusterIssuer")
            if result.stderr:
                console.print(Panel(result.stderr, title="Error", border_style="red"))
            raise typer.Exit(1)

        console.ok(f"ClusterIssuer '{issuer_name}' created")

    # Step 3: Wait for ClusterIssuer to be ready
    console.print("\n[bold]Step 3/3:[/bold] Waiting for ClusterIssuer to be ready...")

    if _wait_for_cluster_issuer(issuer_name, timeout=60):
        console.ok(f"ClusterIssuer '{issuer_name}' is ready")
    else:
        console.warn(f"ClusterIssuer '{issuer_name}' created but not ready yet")
        console.print(
            "[dim]This is normal - it will become ready when you create your first certificate.[/dim]"
        )

    # Success message with next steps
    console.print("\n" + "=" * 60)
    console.ok("TLS setup complete!")
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
        console.warn(
            "Staging certificates are not trusted by browsers. Use only for testing."
        )
        console.warn("  Run without --staging for production certificates.")

    console.print("\n[bold cyan]Manifest saved to:[/bold cyan]")
    console.print(f"  [dim]infra/helm/cert-manager/{issuer_name}.yaml[/dim]")
    console.print(
        "  [dim]Commit this file to version control for GitOps workflows.[/dim]"
    )
