"""Deployment module for managing dev, prod, and (optionally) k8s environments.

Always-present deployers:
- DevDeployer: local development environment with Docker Compose
- ProdDeployer: production environment with Docker Compose

Conditional (only when ``include_k8s_deploy=true`` at template generation):
- HelmDeployer: Kubernetes environment with Helm

The Helm deployer lives in ``cli/deployment/helm_deployer/`` and is excluded
by copier when the k8s toggle is off, so we import it via a try/except
guard. ``HelmDeployer`` and ``DeploymentError`` are re-exported as ``None``
in that case so downstream type hints don't break — only k8s-specific code
paths actually use them.
"""

from .dev_deployer import DevDeployer
from .prod_deployer import ProdDeployer

try:
    from .helm_deployer import DeploymentError, HelmDeployer
except ModuleNotFoundError:
    # k8s subtree excluded; the helm-specific symbols are not needed by
    # dev/prod/fly paths.
    DeploymentError = None  # type: ignore[assignment,misc]
    HelmDeployer = None  # type: ignore[assignment,misc]

__all__ = ["DevDeployer", "ProdDeployer", "HelmDeployer", "DeploymentError"]
