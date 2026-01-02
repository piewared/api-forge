"""Deployment constants and configuration.

This module centralizes all magic strings, paths, and configuration values
used throughout the deployment process.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.utils.paths import get_project_root


@dataclass(frozen=True)
class DeploymentConstants:
    """Constants for Kubernetes/Helm deployment.

    This class provides a centralized location for all deployment-related
    constants, making them easy to find, update, and test.

    All attributes are class-level and immutable.
    """

    # Kubernetes/Helm identifiers
    DEFAULT_NAMESPACE: str = "api-forge-prod"
    HELM_RELEASE_NAME: str = "api-forge"
    HELM_CHART_NAME: str = "api-forge"
    POSTGRES_POD_LABEL: str = "app.kubernetes.io/name=postgres"

    # Timeouts
    HELM_TIMEOUT: str = "10m"
    POD_READY_TIMEOUT: str = "300s"
    REPLICASET_AGE_THRESHOLD_HOURS: float = 1.0

    # Deployment name prefixes for app and worker components
    DEPLOYMENT_PREFIXES: tuple[str, ...] = ("app-", "worker-")

    # Image names
    APP_IMAGE_NAME: str = "api-forge-app"
    POSTGRES_IMAGE_NAME: str = "app_data_postgres_image"
    REDIS_IMAGE_NAME: str = "app_data_redis_image"
    TEMPORAL_IMAGE_NAME: str = "my-temporal-server"

    # Resource names (used for both Docker Compose and Kubernetes)
    APP_RESOURCE_NAME: str = "api-forge-app"
    POSTGRES_RESOURCE_NAME: str = "api-forge-postgres"
    REDIS_RESOURCE_NAME: str = "api-forge-redis"
    TEMPORAL_RESOURCE_NAME: str = "api-forge-temporal"

    # Infrastructure images (tagged with same content-based tag as app)
    @property
    def infra_image_names(self) -> tuple[str, ...]:
        """Get infrastructure image names."""
        return (
            self.POSTGRES_IMAGE_NAME,
            self.REDIS_IMAGE_NAME,
            self.TEMPORAL_IMAGE_NAME,
        )

    # Relative path fragments for project structure
    INFRA_DIR: str = "infra"
    HELM_DIR: str = "helm"
    SECRETS_DIR: str = "secrets"
    DOCKER_DIR: str = "docker"
    DOCKER_PROD_DIR: str = "prod"

    # Default random ephemeral port for connection forwarding
    DEFAULT_EPHEMERAL_PORT: int = 54320

    # Registry URL validation pattern
    # Matches: host.com/path, host:port/path, localhost:5000
    REGISTRY_PATTERN: re.Pattern[str] = re.compile(
        r"^[a-zA-Z0-9][-a-zA-Z0-9.]*[a-zA-Z0-9](:[0-9]+)?(/[a-zA-Z0-9._-]+)*$"
    )


class DeploymentPaths:
    """Path resolver for deployment-related directories and files.

    This class constructs and provides access to all paths needed during
    deployment, derived from the project root.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize deployment paths.

        Args:
            project_root: Path to the project root directory
        """
        self._project_root = project_root
        self._constants = DEFAULT_CONSTANTS

        # Build derived paths
        self.infra = project_root / self._constants.INFRA_DIR
        self.helm_chart = (
            self.infra / self._constants.HELM_DIR / self._constants.HELM_CHART_NAME
        )
        self.helm_scripts = self.helm_chart / "scripts"
        self.helm_files = self.helm_chart / "files"
        self.secrets = self.infra / self._constants.SECRETS_DIR
        self.docker_prod = (
            self.infra / self._constants.DOCKER_DIR / self._constants.DOCKER_PROD_DIR
        )

    @property
    def project_root(self) -> Path:
        """Get path to project root."""
        return self._project_root

    @property
    def templates_dir(self) -> Path:
        """Get path to Helm templates directory."""
        return self.helm_chart / "templates"

    @property
    def postgres_bundled_chart_yaml(self) -> Path:
        """Get path to PostgreSQL StatefulSet YAML (in main chart)."""
        return self.templates_dir / "statefulsets" / "postgres.yaml"

    @property
    def postgres_standalone_chart(self) -> Path:
        """Get path to standalone bundled PostgreSQL Helm chart directory."""
        return self.infra / self._constants.HELM_DIR / "api-forge-bundled-postgres"

    @property
    def config_yaml(self) -> Path:
        """Get path to config.yaml."""
        return self.project_root / "config.yaml"

    @property
    def values_yaml(self) -> Path:
        """Get path to Helm values.yaml."""
        return self.helm_chart / "values.yaml"

    @property
    def bitnami_postgres_values_yaml(self) -> Path:
        """Get path to Bitnami PostgreSQL Helm values.yaml."""
        return self.helm_chart / "values-bitnami-postgres.yaml"

    @property
    def env_file(self) -> Path:
        """Get path to .env file."""
        return self.project_root / ".env"

    @property
    def apply_secrets_script(self) -> Path:
        """Get path to apply-secrets.sh script."""
        return self.helm_scripts / "apply-secrets.sh"

    @property
    def generate_secrets_script(self) -> Path:
        """Get path to generate_secrets.sh script."""
        return self.secrets / "generate_secrets.sh"

    @property
    def secrets_keys_dir(self) -> Path:
        """Get path to secrets keys directory."""
        return self.secrets / "keys"


DEFAULT_CONSTANTS = DeploymentConstants()
DEFAULT_PATHS = DeploymentPaths(project_root=get_project_root())
