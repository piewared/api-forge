"""Deployment CLI commands for dev, prod, and k8s environments."""

import subprocess
import sys
from enum import Enum
from pathlib import Path

import typer
from rich.panel import Panel

from .deployment import DevDeployer, HelmDeployer, ProdDeployer
from .deployment.helm_deployer.image_builder import DeploymentError
from .utils import confirm_destructive_action, console, get_project_root

# Create the deploy command group
deploy_app = typer.Typer(help="🚀 Deployment commands for different environments")


class Environment(str, Enum):
    """Deployment environment options."""

    DEV = "dev"
    PROD = "prod"
    K8S = "k8s"


@deploy_app.command()
def up(
    env: Environment = typer.Argument(
        ..., help="Environment to deploy (dev, prod, or k8s)"
    ),
    force: bool = typer.Option(
        False, "--force", help="Force restart even if services are running (dev only)"
    ),
    no_wait: bool = typer.Option(
        False, "--no-wait", help="Don't wait for services to be ready"
    ),
    start_server: bool = typer.Option(
        True,
        "--start-server/--no-start-server",
        help="Start FastAPI dev server after deploying services (dev only)",
    ),
    skip_build: bool = typer.Option(
        False, "--skip-build", help="Skip building the app image (prod only)"
    ),
    force_recreate: bool = typer.Option(
        False,
        "--force-recreate",
        help="Force recreate containers to pick up new secrets (prod/k8s only)",
    ),
    namespace: str = typer.Option(
        "api-forge-prod", "--namespace", "-n", help="Kubernetes namespace (k8s only)"
    ),
    registry: str = typer.Option(
        None,
        "--registry",
        "-r",
        help="Container registry for remote k8s clusters (e.g., ghcr.io/myuser)",
    ),
) -> None:
    """
    🚀 Deploy the application to the specified environment.

    Environments:
    - dev: Development environment with hot reload
    - prod: Production-like Docker Compose environment
    - k8s: Kubernetes cluster deployment

    For k8s deployments, the cluster type is auto-detected:
    - Minikube/Kind: Images loaded directly into cluster cache
    - Remote clusters: Use --registry to push images to a container registry
    """
    project_root = Path(get_project_root())

    # Display header
    env_name = env.value.upper()
    console.print(
        Panel.fit(
            f"[bold blue]Deploying {env_name} Environment[/bold blue]",
            border_style="blue",
        )
    )

    # Create appropriate deployer and execute deployment
    try:
        deployer: DevDeployer | ProdDeployer | HelmDeployer
        if env == Environment.DEV:
            deployer = DevDeployer(console, project_root)
            deployer.deploy(force=force, no_wait=no_wait, start_server=start_server)

        elif env == Environment.PROD:
            deployer = ProdDeployer(console, project_root)
            deployer.deploy(
                skip_build=skip_build, no_wait=no_wait, force_recreate=force_recreate
            )

        elif env == Environment.K8S:
            deployer = HelmDeployer(console, project_root)
            deployer.deploy(
                namespace=namespace,
                no_wait=no_wait,
                force_recreate=force_recreate,
                registry=registry,
            )

    except DeploymentError as e:
        console.print(f"\n[bold red]❌ Deployment failed: {e.message}[/bold red]\n")
        if e.details:
            console.print(Panel(e.details, title="Details", border_style="red"))
        sys.exit(1)


@deploy_app.command()
def down(
    env: Environment = typer.Argument(
        ..., help="Environment to stop (dev, prod, or k8s)"
    ),
    namespace: str = typer.Option(
        "api-forge-prod", "--namespace", "-n", help="Kubernetes namespace (k8s only)"
    ),
    volumes: bool = typer.Option(
        False, "--volumes", "-v", help="Remove volumes/PVCs along with deployment"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """
    ⏹️  Stop services in the specified environment.

    Environments:
    - dev: Stop development Docker Compose services
    - prod: Stop production Docker Compose services and optionally volumes
    - k8s: Delete Kubernetes deployment and optionally PVCs
    """
    project_root = Path(get_project_root())
    env_name = env.value.upper()

    # Build confirmation details
    if env == Environment.K8S:
        details = f"This will stop all services in namespace '{namespace}'."
    else:
        details = f"This will stop all {env_name} Docker Compose services."

    extra_warning = None
    if volumes:
        extra_warning = (
            "⚠️  --volumes flag is set: ALL DATA WILL BE PERMANENTLY DELETED!\n"
            "   This includes databases, caches, and any persistent storage."
        )

    # Confirm destructive action
    if not confirm_destructive_action(
        action=f"Stop {env_name} environment",
        details=details,
        extra_warning=extra_warning,
        force=yes,
    ):
        console.print("[dim]Operation cancelled.[/dim]")
        raise typer.Exit(0)

    # Display header
    console.print(
        Panel.fit(
            f"[bold red]Stopping {env_name} Environment[/bold red]",
            border_style="red",
        )
    )

    # Create appropriate deployer and execute teardown
    try:
        deployer: DevDeployer | ProdDeployer | HelmDeployer
        if env == Environment.DEV:
            deployer = DevDeployer(console, project_root)
            deployer.teardown(volumes=volumes)

        elif env == Environment.PROD:
            deployer = ProdDeployer(console, project_root)
            deployer.teardown(volumes=volumes)

        elif env == Environment.K8S:
            deployer = HelmDeployer(console, project_root)
            deployer.teardown(namespace=namespace, volumes=volumes)

    except DeploymentError as e:
        console.print(f"\n[bold red]❌ Teardown failed: {e.message}[/bold red]\n")
        if e.details:
            console.print(Panel(e.details, title="Details", border_style="red"))
        sys.exit(1)


@deploy_app.command()
def status(
    env: Environment = typer.Argument(
        ..., help="Environment to check status (dev, prod, or k8s)"
    ),
    namespace: str = typer.Option(
        "api-forge-prod", "--namespace", "-n", help="Kubernetes namespace (k8s only)"
    ),
) -> None:
    """
    📊 Show status of services in the specified environment.

    Environments:
    - dev: Show development Docker Compose services status
    - prod: Show production Docker Compose services status
    - k8s: Show Kubernetes deployment status
    """
    project_root = Path(get_project_root())

    # Create appropriate deployer and show status
    deployer: DevDeployer | ProdDeployer | HelmDeployer
    if env == Environment.DEV:
        deployer = DevDeployer(console, project_root)
        deployer.show_status()

    elif env == Environment.PROD:
        deployer = ProdDeployer(console, project_root)
        deployer.show_status()

    elif env == Environment.K8S:
        deployer = HelmDeployer(console, project_root)
        deployer.show_status(namespace)


@deploy_app.command()
def rotate(
    env: Environment = typer.Argument(
        ..., help="Environment to rotate secrets for (prod or k8s)"
    ),
    redeploy: bool = typer.Option(
        True, "--redeploy/--no-redeploy", help="Automatically redeploy after rotation"
    ),
    force: bool = typer.Option(
        True, "--force/--no-force", help="Force overwrite existing secrets"
    ),
    backup: bool = typer.Option(
        True, "--backup/--no-backup", help="Backup existing secrets before rotation"
    ),
    namespace: str = typer.Option(
        "api-forge-prod", "--namespace", "-n", help="Kubernetes namespace (k8s only)"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """
    🔐 Rotate secrets and optionally redeploy.

    This command:
    1. Generates new cryptographically secure secrets
    2. Optionally backs up existing secrets
    3. Optionally redeploys the environment to pick up new secrets

    Environments:
    - prod: Rotate Docker Compose production secrets
    - k8s: Rotate Kubernetes secrets

    Example usage:
        # Rotate and redeploy prod (default behavior)
        uv run api-forge-cli deploy rotate prod

        # Rotate without redeploying
        uv run api-forge-cli deploy rotate prod --no-redeploy

        # Rotate k8s secrets with backup
        uv run api-forge-cli deploy rotate k8s --backup
    """
    project_root = Path(get_project_root())
    secrets_script = project_root / "infra" / "secrets" / "generate_secrets.sh"

    if not secrets_script.exists():
        console.print(
            f"[red]✗[/red] Secret generation script not found at {secrets_script}"
        )
        raise typer.Exit(1)

    if env == Environment.DEV:
        console.print(
            "[yellow]⚠[/yellow] Secret rotation is not needed for dev environment"
        )
        console.print("   Dev environment uses hardcoded test credentials")
        raise typer.Exit(0)

    # Confirm destructive action
    env_name = env.value.upper()
    details = (
        "This will regenerate all production secrets including:\n"
        "  • Database passwords\n"
        "  • Session signing secrets\n"
        "  • CSRF signing secrets\n"
        "  • OIDC client secrets"
    )
    extra_warning = (
        "⚠️  Existing secrets will be overwritten!\n"
        "   Running services will need to be restarted to use new secrets."
    )
    if not backup:
        extra_warning += "\n   --no-backup: Old secrets will NOT be backed up!"

    if not confirm_destructive_action(
        action=f"Rotate {env_name} secrets",
        details=details,
        extra_warning=extra_warning,
        force=yes,
    ):
        console.print("[dim]Operation cancelled.[/dim]")
        raise typer.Exit(0)

    # Display header
    env_name = env.value.upper()
    console.print(
        Panel.fit(
            f"[bold yellow]🔐 Rotating {env_name} Secrets[/bold yellow]",
            border_style="yellow",
        )
    )

    # Step 1: Backup existing secrets (if requested)
    if backup:
        console.print("\n[bold]Step 1/3:[/bold] Backing up existing secrets...")
        backup_cmd = [str(secrets_script), "--backup-only"]
        try:
            result = subprocess.run(
                backup_cmd,
                cwd=secrets_script.parent,
                capture_output=True,
                text=True,
                check=True,
            )
            console.print("[green]✓[/green] Backup complete")
            if result.stdout:
                console.print(result.stdout)
        except subprocess.CalledProcessError as e:
            console.print(
                f"[yellow]⚠[/yellow] Backup failed (continuing anyway): {e.stderr}"
            )

    # Step 2: Generate new secrets
    console.print(
        f"\n[bold]Step {'2/3' if backup else '1/2'}:[/bold] Generating new secrets..."
    )
    generate_cmd = [str(secrets_script)]
    if force:
        generate_cmd.append("--force")

    try:
        subprocess.run(
            generate_cmd,
            cwd=secrets_script.parent,
            capture_output=False,  # Show output in real-time
            text=True,
            check=True,
        )
        console.print("[green]✓[/green] New secrets generated")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]✗[/red] Secret generation failed: {e}")
        raise typer.Exit(1) from e

    # Step 3: Redeploy (if requested)
    if redeploy:
        console.print(
            f"\n[bold]Step {'3/3' if backup else '2/2'}:[/bold] Redeploying with new secrets..."
        )

        deployer: DevDeployer | ProdDeployer | HelmDeployer
        if env == Environment.PROD:
            deployer = ProdDeployer(console, project_root)
            deployer.deploy(skip_build=False, no_wait=False, force_recreate=True)

        elif env == Environment.K8S:
            deployer = HelmDeployer(console, project_root)
            deployer.deploy(namespace=namespace, no_wait=False, force_recreate=True)

        console.print(
            "\n[bold green]🎉 Secret rotation and redeployment complete![/bold green]"
        )
    else:
        console.print(
            "\n[bold yellow]⚠[/bold yellow] Secrets rotated but not deployed."
        )
        console.print("   Run the following command to deploy with new secrets:")
        if env == Environment.PROD:
            console.print(
                "   [cyan]uv run api-forge-cli deploy up prod --force-recreate[/cyan]"
            )
        elif env == Environment.K8S:
            console.print(
                f"   [cyan]uv run api-forge-cli deploy up k8s --force-recreate -n {namespace}[/cyan]"
            )


@deploy_app.command()
def rollback(
    revision: int = typer.Argument(
        None, help="Revision number to rollback to (default: previous revision)"
    ),
    namespace: str = typer.Option(
        "api-forge-prod", "--namespace", "-n", help="Kubernetes namespace"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """
    ⏪ Rollback Kubernetes deployment to a previous revision.

    This command uses Helm's native rollback functionality to restore
    the deployment to a previous working state.

    Examples:
        # Rollback to the previous revision
        uv run api-forge-cli deploy rollback

        # Rollback to a specific revision
        uv run api-forge-cli deploy rollback 3

        # View revision history first
        uv run api-forge-cli deploy history
    """
    from rich.table import Table

    from .deployment import HelmDeployer

    project_root = Path(get_project_root())
    deployer = HelmDeployer(console, project_root)

    # Get release history
    history = deployer.commands.helm.history(
        deployer.constants.HELM_RELEASE_NAME, namespace
    )

    if not history:
        console.print(
            f"[red]No release history found for '{deployer.constants.HELM_RELEASE_NAME}' "
            f"in namespace '{namespace}'[/red]"
        )
        console.print("\n[dim]Make sure the release exists and you have access.[/dim]")
        raise typer.Exit(1)

    # Show current state
    current = history[-1]
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
        (h for h in history if int(h.get("revision", 0)) == target_revision), None
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
    if not confirm_destructive_action(
        action=f"Rollback to revision {target_revision}",
        details=f"This will restore the deployment in namespace '{namespace}' to revision {target_revision}.",
        extra_warning="Active pods will be replaced with the previous configuration.",
        force=yes,
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
        console.print(
            "\n[dim]Run 'uv run api-forge-cli deploy status k8s' to verify.[/dim]"
        )
    else:
        console.print("\n[bold red]❌ Rollback failed[/bold red]")
        if result.stderr:
            console.print(Panel(result.stderr, title="Error", border_style="red"))
        raise typer.Exit(1)


@deploy_app.command()
def history(
    namespace: str = typer.Option(
        "api-forge-prod", "--namespace", "-n", help="Kubernetes namespace"
    ),
    max_revisions: int = typer.Option(
        10, "--max", "-m", help="Maximum number of revisions to show"
    ),
) -> None:
    """
    📜 Show Kubernetes deployment revision history.

    Displays the Helm release history including revision numbers,
    timestamps, status, and descriptions. Use this to identify
    which revision to rollback to.

    Examples:
        # Show last 10 revisions
        uv run api-forge-cli deploy history

        # Show last 5 revisions
        uv run api-forge-cli deploy history --max 5
    """
    from rich.table import Table

    from .deployment import HelmDeployer

    project_root = Path(get_project_root())
    deployer = HelmDeployer(console, project_root)

    # Get release history
    history_data = deployer.commands.helm.history(
        deployer.constants.HELM_RELEASE_NAME, namespace, max_revisions
    )

    if not history_data:
        console.print(
            f"[yellow]No release history found for '{deployer.constants.HELM_RELEASE_NAME}' "
            f"in namespace '{namespace}'[/yellow]"
        )
        console.print(
            "\n[dim]Deploy first with: uv run api-forge-cli deploy up k8s[/dim]"
        )
        return

    console.print(
        Panel.fit(
            f"[bold cyan]📜 Release History: {deployer.constants.HELM_RELEASE_NAME}[/bold cyan]",
            border_style="cyan",
        )
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Revision", justify="right")
    table.add_column("Updated")
    table.add_column("Status")
    table.add_column("Chart")
    table.add_column("Description")

    for entry in history_data:
        revision = entry.get("revision", "")
        updated = entry.get("updated", "")[:19]  # Trim timezone
        status = entry.get("status", "")
        chart = entry.get("chart", "")
        description = entry.get("description", "")[:40]

        # Color status
        if status == "deployed":
            status_display = f"[green]{status}[/green]"
        elif status in ("failed", "superseded"):
            status_display = f"[red]{status}[/red]"
        elif status == "pending-upgrade":
            status_display = f"[yellow]{status}[/yellow]"
        else:
            status_display = status

        table.add_row(str(revision), updated, status_display, chart, description)

    console.print(table)

    # Show rollback hint
    if len(history_data) > 1:
        console.print(
            "\n[dim]To rollback: uv run api-forge-cli deploy rollback <revision>[/dim]"
        )
