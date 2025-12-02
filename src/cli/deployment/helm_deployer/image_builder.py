"""Docker image building and cluster loading.

This module handles all Docker image operations for deployment:
- Building images with docker-compose
- Generating content-based tags (git SHA or content hash)
- Loading images into local clusters (Minikube, Kind)
- Pushing images to remote registries
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .constants import DeploymentConstants

if TYPE_CHECKING:
    from rich.console import Console
    from rich.progress import Progress

    from ..shell_commands import ShellCommands


class DeploymentError(Exception):
    """Raised when a deployment operation fails."""

    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(message)


class ImageBuilder:
    """Handles Docker image building and cluster loading.

    This class manages the complete image lifecycle for deployments:
    1. Generate deterministic content-based tags
    2. Build images using docker-compose
    3. Load images into the target cluster

    Attributes:
        constants: Deployment configuration constants
        commands: Shell command executor
        console: Rich console for output
    """

    def __init__(
        self,
        commands: ShellCommands,
        console: Console,
        project_root: Path,
        constants: DeploymentConstants | None = None,
    ) -> None:
        """Initialize the image builder.

        Args:
            commands: Shell command executor
            console: Rich console for output
            project_root: Path to project root
            constants: Optional deployment constants (uses defaults if not provided)
        """
        self.commands = commands
        self.console = console
        self.project_root = project_root
        self.constants = constants or DeploymentConstants()

    def build_and_tag_images(
        self,
        progress_factory: type[Progress],
        registry: str | None = None,
    ) -> str:
        """Build Docker images and return content-based tag.

        Creates a deterministic tag based on git commit (if clean) or
        content hash (if dirty/no git). This ensures:
        - Same code = same tag (no duplicate images)
        - Different code = different tag (forces fresh deployment)

        Args:
            progress_factory: Rich Progress class for creating progress bars
            registry: Optional container registry for remote clusters.

        Returns:
            Content-based image tag (e.g., "git-abc1234" or "hash-def5678")
        """
        self.console.print("[bold cyan]🔨 Building Docker images...[/bold cyan]")

        image_tag = self._generate_content_tag()
        self.console.print(f"[dim]Using image tag: {image_tag}[/dim]")

        # Skip rebuild only if ALL images exist with this tag
        if self._all_images_exist(image_tag):
            self.console.print(
                f"[yellow]✓ All images with tag {image_tag} already exist, "
                "skipping build[/yellow]"
            )
            self._load_images_to_cluster(image_tag, registry, progress_factory)
            return image_tag

        # Build and tag images
        with progress_factory(
            transient=True,
        ) as progress:
            task = progress.add_task("Building images...", total=1)
            self.commands.docker.compose_build()
            progress.update(task, completed=1)

        # Tag app image with content-based tag
        self.commands.docker.tag_image(
            f"{self.constants.APP_IMAGE_NAME}:latest",
            f"{self.constants.APP_IMAGE_NAME}:{image_tag}",
        )

        # Tag infrastructure images with the same content-based tag
        # This ensures Kubernetes always pulls the correct version
        for infra_image in self.constants.infra_image_names:
            if self.commands.docker.image_exists(f"{infra_image}:latest"):
                self.commands.docker.tag_image(
                    f"{infra_image}:latest",
                    f"{infra_image}:{image_tag}",
                )
                self.console.print(f"[dim]Tagged {infra_image}:{image_tag}[/dim]")

        self.console.print(
            f"[green]✓ Docker images built and tagged: {image_tag}[/green]"
        )

        self._load_images_to_cluster(image_tag, registry, progress_factory)
        return image_tag

    def _generate_content_tag(self) -> str:
        """Generate a content-based tag for Docker images.

        Priority:
        1. Git commit SHA (only if working tree is clean)
        2. Hash of source files (for dirty git or no git)
        3. Timestamp fallback

        Returns:
            Tag string (e.g., "git-a1b2c3d", "hash-123456789abc", "ts-1234567890")
        """
        # Try git-based tag for clean repositories
        git_status = self.commands.git.get_status()
        if git_status.is_git_repo and git_status.is_clean and git_status.short_sha:
            self.console.print("[dim]✓ Clean git state, using commit SHA[/dim]")
            return f"git-{git_status.short_sha}"
        elif git_status.is_git_repo:
            self.console.print(
                "[dim]⚠ Uncommitted changes detected, using content hash[/dim]"
            )

        # Fall back to content hash
        content_hash = self._compute_source_hash()
        if content_hash:
            return f"hash-{content_hash}"

        # Final fallback: timestamp
        return f"ts-{int(time.time())}"

    def _compute_source_hash(self) -> str | None:
        """Compute a hash of all source files that affect Docker images.

        Includes:
        - Python source files from package directories
        - Infrastructure files (Dockerfiles, shell scripts, configs)

        This ensures any change to app code OR infrastructure scripts
        triggers a new image tag, avoiding stale image issues.

        Returns:
            12-character hex hash, or None if computation fails
        """
        try:
            hasher = hashlib.sha256()
            files_hashed = 0

            # Hash Python source files
            for package_dir in sorted(self._find_package_directories()):
                for py_file in sorted(package_dir.rglob("*.py")):
                    if "__pycache__" not in str(py_file):
                        hasher.update(py_file.read_bytes())
                        files_hashed += 1

            # Hash infrastructure files (Dockerfiles, scripts, configs)
            infra_docker_dir = self.project_root / "infra" / "docker" / "prod"
            if infra_docker_dir.exists():
                for infra_file in sorted(infra_docker_dir.rglob("*")):
                    if infra_file.is_file() and self._is_infra_source_file(infra_file):
                        hasher.update(infra_file.read_bytes())
                        files_hashed += 1

            # Also hash the main Dockerfile and docker-compose files
            for docker_file in ["Dockerfile", "docker-compose.prod.yml"]:
                path = self.project_root / docker_file
                if path.exists():
                    hasher.update(path.read_bytes())
                    files_hashed += 1

            if files_hashed == 0:
                return None

            return hasher.hexdigest()[:12]
        except Exception as e:
            self.console.print(f"[dim]Could not compute content hash: {e}[/dim]")
            return None

    def _is_infra_source_file(self, path: Path) -> bool:
        """Check if a file is an infrastructure source file worth hashing.

        Args:
            path: Path to check

        Returns:
            True if the file should be included in the content hash
        """
        # Include these extensions
        include_extensions = {
            ".sh",  # Shell scripts
            ".sql",  # SQL init scripts
            ".conf",  # Config files (postgresql.conf, redis.conf)
            ".yaml",  # YAML configs
            ".yml",  # YAML configs
            ".json",  # JSON configs
            ".toml",  # TOML configs
            ".py",  # Python scripts
        }

        # Include Dockerfiles (no extension)
        if path.name in ("Dockerfile", "Dockerfile.dev", "Dockerfile.prod"):
            return True

        return path.suffix.lower() in include_extensions

    def _find_package_directories(self) -> list[Path]:
        """Find Python package directories in the project root.

        Returns:
            List of paths to directories containing __init__.py
        """
        excluded_dirs = {
            ".git",
            "__pycache__",
            ".pytest_cache",
            "tests",
            "docs",
            "infra",
            "data",
            ".venv",
            "venv",
        }

        packages = []
        for path in self.project_root.iterdir():
            if path.is_dir() and path.name not in excluded_dirs:
                if (path / "__init__.py").exists():
                    packages.append(path)
        return packages

    def _all_images_exist(self, image_tag: str) -> bool:
        """Check if all Docker images exist with the given tag.

        Args:
            image_tag: The tag to check for

        Returns:
            True if ALL images (app + infra) exist with this tag
        """
        all_images = self._get_all_images(image_tag)
        for image in all_images:
            if not self.commands.docker.image_exists(image):
                self.console.print(f"[dim]Image {image} not found, will rebuild[/dim]")
                return False
        return True

    def _get_all_images(self, image_tag: str) -> list[str]:
        """Get list of all Docker images to deploy.

        Args:
            image_tag: Tag for all images (app and infra use same tag)

        Returns:
            List of fully qualified image names with tags
        """
        images = [f"{self.constants.APP_IMAGE_NAME}:{image_tag}"]
        # Use the same content-based tag for infra images to avoid stale image issues
        images.extend(
            f"{name}:{image_tag}" for name in self.constants.infra_image_names
        )
        return images

    def _load_images_to_cluster(
        self,
        image_tag: str,
        registry: str | None,
        progress_factory: type[Progress],
    ) -> None:
        """Load Docker images into the Kubernetes cluster.

        Automatically detects the cluster type and uses the appropriate
        method to make images available:
        - Minikube: Uses `minikube image load` to load directly
        - Kind: Uses `kind load docker-image` to load directly
        - Remote clusters: Pushes to container registry (requires registry arg)

        Args:
            image_tag: Tag for the app image (infrastructure images use :latest)
            registry: Container registry URL for remote clusters
            progress_factory: Rich Progress class for creating progress bars
        """
        context = self.commands.kubectl.get_current_context()

        # Determine cluster type and loading strategy
        if self.commands.kubectl.is_minikube_context():
            self._load_images_minikube(image_tag, progress_factory)
        elif "kind" in context.lower():
            self._load_images_kind(image_tag, progress_factory)
        elif registry:
            self._push_images_to_registry(image_tag, registry, progress_factory)
        else:
            raise DeploymentError(
                f"Remote cluster '{context}' detected but no registry specified",
                details="Use --registry to push images to a container registry.\n"
                "Example: --registry ghcr.io/myuser",
            )

    def _load_images_minikube(
        self, image_tag: str, progress_factory: type[Progress]
    ) -> None:
        """Load Docker images into Minikube's internal registry."""
        self.console.print("[bold cyan]📦 Loading images into Minikube...[/bold cyan]")

        images = self._get_all_images(image_tag)

        with progress_factory(transient=True) as progress:
            task = progress.add_task("Loading images...", total=len(images))
            for image in images:
                self.commands.docker.minikube_load_image(image)
                progress.update(task, advance=1)

        self.console.print(
            f"[green]✓ Images loaded into Minikube with tag: {image_tag}[/green]"
        )

    def _load_images_kind(
        self, image_tag: str, progress_factory: type[Progress]
    ) -> None:
        """Load Docker images into Kind cluster."""
        self.console.print("[bold cyan]📦 Loading images into Kind...[/bold cyan]")

        images = self._get_all_images(image_tag)

        with progress_factory(transient=True) as progress:
            task = progress.add_task("Loading images...", total=len(images))
            for image in images:
                self.commands.docker.kind_load_image(image)
                progress.update(task, advance=1)

        self.console.print(
            f"[green]✓ Images loaded into Kind with tag: {image_tag}[/green]"
        )

    def _push_images_to_registry(
        self,
        image_tag: str,
        registry: str,
        progress_factory: type[Progress],
    ) -> None:
        """Push Docker images to a remote container registry."""
        self.console.print(f"[bold cyan]📦 Pushing images to {registry}...[/bold cyan]")

        # Build list of (local_image, remote_image) pairs
        local_images = self._get_all_images(image_tag)
        image_pairs = [
            (local, f"{registry}/{local.split(':')[0]}:{local.split(':')[1]}")
            for local in local_images
        ]

        with progress_factory(transient=True) as progress:
            task = progress.add_task("Pushing images...", total=len(image_pairs) * 2)

            for local_image, remote_image in image_pairs:
                # Tag for registry
                self.commands.docker.tag_image(local_image, remote_image)
                progress.update(task, advance=1)

                # Push to registry
                self.commands.docker.push_image(remote_image)
                progress.update(task, advance=1)

        self.console.print(f"[green]✓ Images pushed to {registry}[/green]")
