"""Unit tests for the image builder module."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.cli.deployment.helm_deployer.constants import DeploymentConstants
from src.cli.deployment.helm_deployer.image_builder import DeploymentError, ImageBuilder


class TestDeploymentError:
    """Tests for the DeploymentError exception."""

    def test_error_with_message_only(self) -> None:
        """DeploymentError can be created with just a message."""
        error = DeploymentError("Something failed")
        assert error.message == "Something failed"
        assert error.details is None
        assert str(error) == "Something failed"

    def test_error_with_details(self) -> None:
        """DeploymentError can include detailed recovery information."""
        error = DeploymentError(
            "Build failed",
            details="Try running 'docker system prune' to free up space",
        )
        assert error.message == "Build failed"
        assert error.details == "Try running 'docker system prune' to free up space"


class MockProgress:
    """Mock Rich Progress class for testing."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> MockProgress:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def add_task(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def update(self, *args: Any, **kwargs: Any) -> None:
        pass


class TestImageBuilder:
    """Tests for the ImageBuilder class."""

    @pytest.fixture
    def mock_commands(self) -> MagicMock:
        """Create a mock shell commands instance."""
        commands = MagicMock()
        commands.docker = MagicMock()
        commands.kubectl = MagicMock()
        commands.git = MagicMock()
        return commands

    @pytest.fixture
    def mock_console(self) -> MagicMock:
        """Create a mock Rich console."""
        return MagicMock()

    @pytest.fixture
    def image_builder(
        self, mock_commands: MagicMock, mock_console: MagicMock, tmp_path: Path
    ) -> ImageBuilder:
        """Create an ImageBuilder instance with mocked dependencies."""
        return ImageBuilder(
            commands=mock_commands,
            console=mock_console,
            project_root=tmp_path,
            constants=DeploymentConstants(),
        )

    def test_get_all_images_returns_app_and_worker(
        self, image_builder: ImageBuilder
    ) -> None:
        """_get_all_images should return both app and worker images."""
        images = image_builder._get_all_images("abc123")

        assert len(images) >= 2
        assert any("app" in img.lower() or "api-forge" in img.lower() for img in images)
        assert all("abc123" in img for img in images)

    def test_cluster_type_detection_minikube(
        self, image_builder: ImageBuilder, mock_commands: MagicMock
    ) -> None:
        """Should detect Minikube cluster correctly."""
        mock_commands.kubectl.is_minikube_context.return_value = True

        result = mock_commands.kubectl.is_minikube_context()
        assert result is True

    def test_cluster_type_detection_kind(
        self, image_builder: ImageBuilder, mock_commands: MagicMock
    ) -> None:
        """Should detect Kind cluster correctly."""
        mock_commands.kubectl.is_minikube_context.return_value = False
        mock_commands.kubectl.current_context.return_value = "kind-my-cluster"

        result = mock_commands.kubectl.current_context()
        assert "kind" in result.lower()

    def test_remote_cluster_without_registry_raises(
        self,
        image_builder: ImageBuilder,
        mock_commands: MagicMock,
    ) -> None:
        """Deploying to remote cluster without registry should raise error."""
        mock_commands.kubectl.is_minikube_context.return_value = False
        mock_commands.kubectl.current_context.return_value = "gke-my-cluster"

        with pytest.raises(DeploymentError) as exc_info:
            image_builder._load_images_to_cluster(
                "abc123",
                None,
                MockProgress,  # type: ignore[arg-type]
            )

        assert "registry" in exc_info.value.message.lower()
        assert exc_info.value.details is not None

    def test_load_images_minikube(
        self,
        image_builder: ImageBuilder,
        mock_commands: MagicMock,
    ) -> None:
        """Should load images into Minikube using minikube load."""
        mock_commands.kubectl.is_minikube_context.return_value = True
        mock_commands.docker.minikube_load_image.return_value = None

        image_builder._load_images_to_cluster(
            "abc123",
            None,
            MockProgress,  # type: ignore[arg-type]
        )

        # Should call minikube load for each image
        assert mock_commands.docker.minikube_load_image.called

    def test_load_images_kind(
        self,
        image_builder: ImageBuilder,
        mock_commands: MagicMock,
    ) -> None:
        """Should load images into Kind using kind load."""
        mock_commands.kubectl.is_minikube_context.return_value = False
        # Need to mock get_current_context (note: without underscore)
        mock_commands.kubectl.get_current_context.return_value = "kind-test"
        mock_commands.docker.kind_load_image.return_value = None

        image_builder._load_images_to_cluster(
            "abc123",
            None,
            MockProgress,  # type: ignore[arg-type]
        )

        # Should call kind load for each image
        assert mock_commands.docker.kind_load_image.called

    def test_push_images_to_registry(
        self,
        image_builder: ImageBuilder,
        mock_commands: MagicMock,
    ) -> None:
        """Should tag and push images when registry is provided."""
        mock_commands.kubectl.is_minikube_context.return_value = False
        mock_commands.kubectl.current_context.return_value = "gke-prod"
        mock_commands.docker.tag_image.return_value = MagicMock(success=True)
        mock_commands.docker.push_image.return_value = MagicMock(success=True)

        image_builder._load_images_to_cluster(
            "abc123",
            "ghcr.io/myuser",
            MockProgress,  # type: ignore[arg-type]
        )

        # Should tag and push each image
        assert mock_commands.docker.tag_image.called
        assert mock_commands.docker.push_image.called

    def test_build_and_tag_images_success(
        self,
        image_builder: ImageBuilder,
        mock_commands: MagicMock,
        tmp_path: Path,
    ) -> None:
        """build_and_tag_images should build and return the tag."""
        # Create test files
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "app.py").write_text("print('hello')")
        (tmp_path / "Dockerfile").write_text("FROM python:3.13")

        # Mock git check to return dirty (no git)
        mock_commands.git.is_clean.return_value = False
        mock_commands.docker.compose_build.return_value = None
        mock_commands.docker.tag_image.return_value = MagicMock(success=True)
        mock_commands.docker.image_exists.return_value = False
        mock_commands.kubectl.is_minikube_context.return_value = True
        mock_commands.docker.minikube_load_image.return_value = None

        tag = image_builder.build_and_tag_images(MockProgress)  # type: ignore[arg-type]

        assert tag is not None
        assert isinstance(tag, str)


class TestImageBuilderIntegration:
    """Integration-like tests that test multiple components together."""

    @pytest.fixture
    def full_project_setup(self, tmp_path: Path) -> Path:
        """Create a minimal project structure for testing."""
        # Create directories
        (tmp_path / "src" / "app").mkdir(parents=True)
        (tmp_path / "infra" / "docker" / "prod").mkdir(parents=True)

        # Create files
        (tmp_path / "src" / "app" / "__init__.py").write_text("")
        (tmp_path / "src" / "app" / "main.py").write_text("print('main')")
        (tmp_path / "Dockerfile").write_text("FROM python:3.13\nCMD ['python']")
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        return tmp_path

    def test_full_build_flow_for_minikube(self, full_project_setup: Path) -> None:
        """Test the full build flow targeting Minikube."""
        mock_commands = MagicMock()
        mock_commands.git.is_clean.return_value = False
        mock_commands.docker.compose_build.return_value = None
        mock_commands.docker.tag_image.return_value = MagicMock(success=True)
        mock_commands.docker.image_exists.return_value = False
        mock_commands.kubectl.is_minikube_context.return_value = True
        mock_commands.docker.minikube_load_image.return_value = None

        mock_console = MagicMock()

        builder = ImageBuilder(
            commands=mock_commands,
            console=mock_console,
            project_root=full_project_setup,
        )

        tag = builder.build_and_tag_images(MockProgress)  # type: ignore[arg-type]

        assert tag is not None
        assert mock_commands.docker.compose_build.called
        assert mock_commands.docker.minikube_load_image.called
