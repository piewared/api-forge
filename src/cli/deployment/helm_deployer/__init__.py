"""Helm deployer package for Kubernetes deployments.

This package provides a modular approach to Kubernetes deployment via Helm,
with each concern separated into its own module:

- image_builder: Docker image building and loading to clusters
- secret_manager: Secret generation and deployment
- config_sync: Configuration synchronization between config.yaml and values.yaml
- helm_release: Helm chart deployment and release management
- cleanup: Post-deployment cleanup of old resources
- validator: Pre-deployment validation and cleanup prompts

The HelmDeployer class in deployer.py orchestrates these components to
provide a complete deployment workflow.

Usage:
    from src.cli.deployment.helm_deployer import HelmDeployer

    deployer = HelmDeployer(console, project_root)
    deployer.deploy(namespace="my-namespace")
"""

from .cleanup import CleanupManager
from .config_sync import ConfigSynchronizer
from .deployer import DeploymentError, HelmDeployer
from .helm_release import HelmReleaseManager
from .image_builder import ImageBuilder
from .secret_manager import SecretManager
from .validator import DeploymentValidator, ValidationResult, ValidationSeverity

__all__ = [
    "HelmDeployer",
    "DeploymentError",
    # Component classes for testing/extension
    "ImageBuilder",
    "SecretManager",
    "ConfigSynchronizer",
    "HelmReleaseManager",
    "CleanupManager",
    "DeploymentValidator",
    "ValidationResult",
    "ValidationSeverity",
]
