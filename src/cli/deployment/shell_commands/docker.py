"""Docker command abstractions.

This module provides commands for Docker image and compose operations,
including building, tagging, pushing, and loading images into local clusters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .types import CommandResult

if TYPE_CHECKING:
    from .runner import CommandRunner


class DockerCommands:
    """Docker-related shell commands.

    Provides operations for:
    - Image management (build, tag, push, check existence)
    - Docker Compose builds
    - Loading images into local Kubernetes clusters (Minikube, Kind)
    """

    def __init__(self, runner: CommandRunner) -> None:
        """Initialize Docker commands.

        Args:
            runner: Command runner for executing shell commands
        """
        self._runner = runner

    # =========================================================================
    # Image Management
    # =========================================================================

    def image_exists(self, image_tag: str) -> bool:
        """Check if a Docker image with the given tag exists locally.

        Args:
            image_tag: Full image tag (e.g., "api-forge-app:git-abc1234")

        Returns:
            True if image exists, False otherwise

        Example:
            >>> docker.image_exists("api-forge-app:latest")
            True
        """
        result = self._runner.run(["docker", "images", "-q", image_tag])
        return bool(result.stdout.strip())

    def tag_image(self, source_tag: str, target_tag: str) -> CommandResult:
        """Tag a Docker image with a new tag.

        Args:
            source_tag: Existing image tag (e.g., "api-forge-app:latest")
            target_tag: New tag to apply (e.g., "api-forge-app:git-abc1234")

        Returns:
            CommandResult with tagging status

        Example:
            >>> docker.tag_image("api-forge-app:latest", "api-forge-app:v1.0.0")
        """
        return self._runner.run(["docker", "tag", source_tag, target_tag])

    def push_image(self, image_tag: str) -> CommandResult:
        """Push a Docker image to a remote registry.

        Args:
            image_tag: Full image tag including registry
                      (e.g., "registry.example.com/app:v1")

        Returns:
            CommandResult with push status
        """
        return self._runner.run(["docker", "push", image_tag])

    # =========================================================================
    # Docker Compose
    # =========================================================================

    def compose_build(
        self, compose_file: str = "docker-compose.prod.yml"
    ) -> CommandResult:
        """Build images using docker compose.

        Args:
            compose_file: Path to the docker-compose file (relative to project root)

        Returns:
            CommandResult with build status

        Example:
            >>> result = docker.compose_build()
            >>> if result.success:
            ...     print("Build complete")
        """
        from src.infra.utils.service_config import is_bundled_postgres_enabled

        # Determine which services to build based on configuration
        services_to_build = ["app", "worker", "redis", "temporal", "temporal-web"]

        # Only build postgres if bundled postgres is enabled
        # (postgres service is in a profile and causes dependency errors if not needed)
        if is_bundled_postgres_enabled():
            services_to_build.append("postgres")

        return self._runner.run(
            ["docker", "compose", "-f", compose_file, "build"] + services_to_build,
            capture_output=False,
        )

    # =========================================================================
    # Local Cluster Image Loading
    # =========================================================================

    def minikube_load_image(self, image_tag: str) -> CommandResult:
        """Load a Docker image into Minikube's internal registry.

        This is required for Minikube to access locally-built images that
        aren't in a remote registry.

        Args:
            image_tag: Full image tag to load (e.g., "api-forge-app:git-abc1234")

        Returns:
            CommandResult with load status

        Note:
            This command may take several seconds depending on image size.
        """
        return self._runner.run(["minikube", "image", "load", image_tag])

    def kind_load_image(
        self, image_tag: str, cluster_name: str = "kind"
    ) -> CommandResult:
        """Load a Docker image into a Kind cluster.

        Args:
            image_tag: Full image tag to load
            cluster_name: Name of the Kind cluster (default: "kind")

        Returns:
            CommandResult with load status
        """
        return self._runner.run(
            ["kind", "load", "docker-image", image_tag, "--name", cluster_name]
        )
