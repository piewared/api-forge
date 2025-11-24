"""Deployment CLI commands for dev, prod, and k8s environments."""

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
    env: Environment = typer.Argument(..., help="Environment to deploy (dev, prod, or k8s)"),
    force: bool = typer.Option(
        False, "--force", help="Force restart even if services are running (dev only)"
    ),
    no_wait: bool = typer.Option(False, "--no-wait", help="Don't wait for services to be ready"),
    skip_build: bool = typer.Option(
        False, "--skip-build", help="Skip building the app image (prod only)"
    ),
    force_recreate: bool = typer.Option(
        False, "--force-recreate", help="Force recreate containers to pick up new secrets (prod/k8s only)"
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
    if env == Environment.DEV:
        deployer = DevDeployer(console, project_root)
        deployer.deploy(force=force, no_wait=no_wait)

    elif env == Environment.PROD:
        deployer = ProdDeployer(console, project_root)
        deployer.deploy(skip_build=skip_build, no_wait=no_wait, force_recreate=force_recreate)

    elif env == Environment.K8S:
        deployer = K8sDeployer(console, project_root)
        deployer.deploy(namespace=namespace, no_wait=no_wait, force_recreate=force_recreate)


@deploy_app.command()
def down(
    env: Environment = typer.Argument(..., help="Environment to stop (dev, prod, or k8s)"),
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
    env: Environment = typer.Argument(..., help="Environment to check status (dev, prod, or k8s)"),
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
    if env == Environment.DEV:
        deployer = DevDeployer(console, project_root)
        deployer.show_status()

    elif env == Environment.PROD:
        deployer = ProdDeployer(console, project_root)
        deployer.show_status()

    elif env == Environment.K8S:
        deployer = K8sDeployer(console, project_root)
        deployer.show_status(namespace)
