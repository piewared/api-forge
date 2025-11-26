"""Deployment CLI commands for dev, prod, and k8s environments."""

import subprocess
from enum import Enum
from pathlib import Path

import typer
from rich.panel import Panel

from .deployment import DevDeployer, K8sDeployer, ProdDeployer
from .utils import console, get_project_root

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
) -> None:
    """
    🚀 Deploy the application to the specified environment.

    Environments:
    - dev: Development environment with hot reload
    - prod: Production-like Docker Compose environment
    - k8s: Kubernetes cluster deployment
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
    deployer: DevDeployer | ProdDeployer | K8sDeployer
    if env == Environment.DEV:
        deployer = DevDeployer(console, project_root)
        deployer.deploy(force=force, no_wait=no_wait)

    elif env == Environment.PROD:
        deployer = ProdDeployer(console, project_root)
        deployer.deploy(
            skip_build=skip_build, no_wait=no_wait, force_recreate=force_recreate
        )

    elif env == Environment.K8S:
        deployer = K8sDeployer(console, project_root)
        deployer.deploy(
            namespace=namespace, no_wait=no_wait, force_recreate=force_recreate
        )


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
) -> None:
    """
    ⏹️  Stop services in the specified environment.

    Environments:
    - dev: Stop development Docker Compose services
    - prod: Stop production Docker Compose services and optionally volumes
    - k8s: Delete Kubernetes deployment and optionally PVCs
    """
    project_root = Path(get_project_root())

    # Display header
    env_name = env.value.upper()
    console.print(
        Panel.fit(
            f"[bold red]Stopping {env_name} Environment[/bold red]",
            border_style="red",
        )
    )

    # Create appropriate deployer and execute teardown
    deployer: DevDeployer | ProdDeployer | K8sDeployer
    if env == Environment.DEV:
        deployer = DevDeployer(console, project_root)
        deployer.teardown(volumes=volumes)

    elif env == Environment.PROD:
        deployer = ProdDeployer(console, project_root)
        deployer.teardown(volumes=volumes)

    elif env == Environment.K8S:
        deployer = K8sDeployer(console, project_root)
        deployer.teardown(namespace=namespace, volumes=volumes)


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
    deployer: DevDeployer | ProdDeployer | K8sDeployer
    if env == Environment.DEV:
        deployer = DevDeployer(console, project_root)
        deployer.show_status()

    elif env == Environment.PROD:
        deployer = ProdDeployer(console, project_root)
        deployer.show_status()

    elif env == Environment.K8S:
        deployer = K8sDeployer(console, project_root)
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

        deployer: DevDeployer | ProdDeployer | K8sDeployer
        if env == Environment.PROD:
            deployer = ProdDeployer(console, project_root)
            deployer.deploy(skip_build=False, no_wait=False, force_recreate=True)

        elif env == Environment.K8S:
            deployer = K8sDeployer(console, project_root)
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
