"""FKS pod log streaming command."""

from __future__ import annotations

import os
from typing import Annotated

import typer

from src.cli.context import get_cli_context
from src.cli.shared.console import console, with_error_handling
from src.cli.shared.fly import check_prerequisites, get_fly_controller

from . import fks_app
from ._helpers import ensure_kubeconfig, select_fks_cluster


@fks_app.command()
@with_error_handling
def logs(
    pod: Annotated[
        str | None,
        typer.Argument(
            help="Pod name or label selector (e.g., 'app=api-forge')",
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
    container: Annotated[
        str | None,
        typer.Option(
            "--container",
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
    """View logs from FKS pods.

    Shows logs from pods in the deployment. If no pod is specified,
    shows logs from all pods with the app label.

    Examples:
        uv run api-forge-cli fly logs --cluster my-cluster
        uv run api-forge-cli fly logs api-forge-abc123 -c my-cluster
        uv run api-forge-cli fly logs -c my-cluster -f  # Follow logs
        uv run api-forge-cli fly logs -c my-cluster --previous
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    cluster_info = select_fks_cluster(controller, cluster)
    cluster_name = cluster_info.get("name", "")

    kubeconfig_path = ensure_kubeconfig(controller, cluster_name)

    original_kubeconfig = os.environ.get("KUBECONFIG")
    os.environ["KUBECONFIG"] = str(kubeconfig_path)

    try:
        console.info(f"Cluster: {cluster_name} | Namespace: {namespace}")
        console.print()

        # Determine label selector for non-specific pod requests
        label_selector = "app=api-forge" if not pod else None

        k8s_controller = get_cli_context().k8s_controller
        result = k8s_controller.get_pod_logs(
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
            console.error(result.stderr)

    except KeyboardInterrupt:
        console.info("Log streaming stopped")
    finally:
        if original_kubeconfig:
            os.environ["KUBECONFIG"] = original_kubeconfig
        else:
            os.environ.pop("KUBECONFIG", None)
