"""Shell command abstractions for Kubernetes/Helm deployment operations.

This package provides a clean, well-documented interface for shell commands used
during deployment. It is organized into specialized modules for each tool:

- docker: Docker image and compose operations
- helm: Helm release management
- kubectl: Kubernetes resource management
- git: Git repository operations

Design Principles:
- Single Responsibility: Each module focuses on one tool
- Self-Documenting: Function names describe what they do
- Consistent Return Types: Functions return typed results or raise exceptions
- Separation of Concerns: Commands are decoupled from workflow logic

Usage:
    from src.cli.deployment.shell_commands import ShellCommands

    commands = ShellCommands(project_root=Path("."))
    if commands.docker.image_exists("my-app:latest"):
        print("Image already built")
"""

from pathlib import Path

from src.utils.paths import get_project_root

from .docker import DockerCommands
from .git import GitCommands
from .helm import HelmCommands
from .runner import CommandRunner
from .types import (
    CommandResult,
    GitStatus,
    HelmRelease,
    ReplicaSetInfo,
    calculate_replicaset_age_hours,
)


class ShellCommands:
    """Unified interface for all shell command operations.

    This class provides a facade over the specialized command modules,
    offering a single point of access for deployment operations while
    maintaining separation of concerns internally.

    Attributes:
        docker: Docker-related commands
        helm: Helm-related commands
        kubectl: Kubernetes kubectl commands
        git: Git repository commands

    Example:
        >>> commands = ShellCommands(Path("."))
        >>> if commands.docker.image_exists("app:latest"):
        ...     commands.helm.upgrade_install("my-release", chart_path, namespace)
    """

    def __init__(self, project_root: Path | None = None) -> None:
        """Initialize the shell commands executor.

        Args:
            project_root: Path to the project root directory.
                         Commands will be executed from this directory by default.
        """
        self._project_root = Path(project_root) if project_root else get_project_root()
        self._runner = CommandRunner(self._project_root)

        # Initialize specialized command modules
        self.docker = DockerCommands(self._runner)
        self.helm = HelmCommands(self._runner)
        self.git = GitCommands(self._runner)

    @property
    def project_root(self) -> Path:
        """Get the project root path."""
        return self._project_root

    # =========================================================================
    # Backward Compatibility Methods
    # =========================================================================
    # These methods delegate to the specialized modules for backward
    # compatibility with existing code. New code should use the module
    # properties directly (e.g., commands.docker.image_exists).

    # Docker commands
    def docker_image_exists(self, image_tag: str) -> bool:
        """Check if a Docker image exists. See docker.image_exists."""
        return self.docker.image_exists(image_tag)

    def docker_compose_build(
        self, compose_file: str = "docker-compose.prod.yml"
    ) -> CommandResult:
        """Build with docker compose. See docker.compose_build."""
        return self.docker.compose_build(compose_file)

    def docker_tag_image(self, source_tag: str, target_tag: str) -> CommandResult:
        """Tag a Docker image. See docker.tag_image."""
        return self.docker.tag_image(source_tag, target_tag)

    def docker_push_image(self, image_tag: str) -> CommandResult:
        """Push a Docker image. See docker.push_image."""
        return self.docker.push_image(image_tag)

    # Image loading
    def minikube_load_image(self, image_tag: str) -> CommandResult:
        """Load image into Minikube. See docker.minikube_load_image."""
        return self.docker.minikube_load_image(image_tag)

    def kind_load_image(
        self, image_tag: str, cluster_name: str = "kind"
    ) -> CommandResult:
        """Load image into Kind. See docker.kind_load_image."""
        return self.docker.kind_load_image(image_tag, cluster_name)

    # Helm commands
    def helm_upgrade_install(self, *args, **kwargs) -> CommandResult:  # type: ignore[no-untyped-def]
        """Deploy or upgrade a Helm release. See helm.upgrade_install."""
        return self.helm.upgrade_install(*args, **kwargs)

    def helm_uninstall(self, *args, **kwargs) -> CommandResult:  # type: ignore[no-untyped-def]
        """Uninstall a Helm release. See helm.uninstall."""
        return self.helm.uninstall(*args, **kwargs)

    def helm_list_releases(self, *args, **kwargs) -> list[HelmRelease]:  # type: ignore[no-untyped-def]
        """List Helm releases. See helm.list_releases."""
        return self.helm.list_releases(*args, **kwargs)

    def helm_get_stuck_releases(self, *args, **kwargs) -> list[HelmRelease]:  # type: ignore[no-untyped-def]
        """Get stuck Helm releases. See helm.get_stuck_releases."""
        return self.helm.get_stuck_releases(*args, **kwargs)

    # Git commands
    def git_get_status(self) -> GitStatus:
        """Get git status. See git.get_status."""
        return self.git.get_status()

    # Script execution
    def run_bash_script(
        self, script_path: Path, args: list[str] | None = None
    ) -> CommandResult:
        """Execute a bash script."""
        cmd = ["bash", str(script_path)]
        if args:
            cmd.extend(args)
        return self._runner.run(cmd, capture_output=False)


__all__ = [
    "ShellCommands",
    "CommandResult",
    "HelmRelease",
    "ReplicaSetInfo",
    "GitStatus",
    "calculate_replicaset_age_hours",
    # Specialized command classes for direct usage
    "DockerCommands",
    "HelmCommands",
    "GitCommands",
    "CommandRunner",
]
