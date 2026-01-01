"""Tests for CLI context dependency injection."""

from pathlib import Path
from unittest.mock import Mock, patch

import click
import pytest
import typer

from src.cli.context import CLIContext, build_cli_context, get_cli_context


def test_cli_context_is_immutable():
    """Test that CLIContext is frozen/immutable."""
    ctx = CLIContext(
        console=Mock(),
        project_root=Path("/test"),
        commands=Mock(),
        k8s_controller=Mock(),
        constants=Mock(),
        paths=Mock(),
    )

    with pytest.raises(AttributeError):
        ctx.console = Mock()  # type: ignore[attr-defined]


@patch("src.cli.context.get_project_root")
@patch("src.cli.context.get_k8s_controller_sync")
def test_build_cli_context_creates_all_dependencies(mock_k8s_controller, mock_get_root):
    """Test that build_cli_context creates all required dependencies."""
    mock_get_root.return_value = Path("/test/project")
    mock_k8s_controller.return_value = Mock()

    ctx = build_cli_context()

    assert ctx.console is not None
    assert ctx.project_root == Path("/test/project")
    assert ctx.commands is not None
    assert ctx.k8s_controller is not None
    assert ctx.constants is not None
    assert ctx.paths is not None


@patch("src.cli.context.get_project_root")
def test_build_cli_context_paths_uses_project_root(mock_get_root):
    """Test that DeploymentPaths is initialized with project root."""
    mock_get_root.return_value = Path("/test/project")

    ctx = build_cli_context()

    # Paths should have project_root as base
    assert hasattr(ctx.paths, "project_root")


def test_get_cli_context_from_typer_context():
    """Test that get_cli_context retrieves from Typer context."""
    mock_ctx_obj = CLIContext(
        console=Mock(),
        project_root=Path("/test"),
        commands=Mock(),
        k8s_controller=Mock(),
        constants=Mock(),
        paths=Mock(),
    )

    typer_ctx = Mock(spec=typer.Context)
    typer_ctx.obj = mock_ctx_obj

    result = get_cli_context(typer_ctx)

    assert result is mock_ctx_obj


def test_get_cli_context_with_none_falls_back():
    """Test that get_cli_context creates new context when ctx is None."""
    with patch("src.cli.context.build_cli_context") as mock_build:
        mock_build.return_value = Mock(spec=CLIContext)

        get_cli_context(None)

        # Should have called build_cli_context
        mock_build.assert_called_once()


def test_get_cli_context_with_invalid_obj_falls_back():
    """Test that get_cli_context falls back when ctx.obj is not CLIContext."""
    typer_ctx = Mock(spec=typer.Context)
    typer_ctx.obj = "invalid"  # Not a CLIContext

    with patch("src.cli.context.build_cli_context") as mock_build:
        mock_build.return_value = Mock(spec=CLIContext)

        get_cli_context(typer_ctx)

        # Should have called build_cli_context
        mock_build.assert_called_once()


@patch("click.get_current_context")
def test_get_cli_context_uses_click_context_as_fallback(mock_get_click_ctx):
    """Test that get_cli_context uses click context when typer ctx is None."""
    mock_ctx_obj = CLIContext(
        console=Mock(),
        project_root=Path("/test"),
        commands=Mock(),
        k8s_controller=Mock(),
        constants=Mock(),
        paths=Mock(),
    )

    mock_click_context = Mock()
    mock_click_context.obj = mock_ctx_obj
    mock_get_click_ctx.return_value = mock_click_context

    result = get_cli_context(None)

    assert result is mock_ctx_obj
    mock_get_click_ctx.assert_called_once_with(silent=True)


@patch("src.cli.context.ShellCommands")
@patch("src.cli.context.get_project_root")
def test_cli_context_shell_commands_initialized_with_project_root(
    mock_get_root, mock_shell_commands
):
    """Test that ShellCommands is initialized with project_root."""
    mock_get_root.return_value = Path("/test/project")

    build_cli_context()

    mock_shell_commands.assert_called_once_with(Path("/test/project"))


def test_cli_context_all_fields_accessible():
    """Test that all CLIContext fields are accessible."""
    ctx = CLIContext(
        console=Mock(),
        project_root=Path("/test"),
        commands=Mock(),
        k8s_controller=Mock(),
        constants=Mock(),
        paths=Mock(),
    )

    # All fields should be accessible
    assert ctx.console is not None
    assert ctx.project_root == Path("/test")
    assert ctx.commands is not None
    assert ctx.k8s_controller is not None
    assert ctx.constants is not None
    assert ctx.paths is not None


@patch("src.cli.context.DeploymentConstants")
@patch("src.cli.context.DeploymentPaths")
@patch("src.cli.context.get_project_root")
def test_cli_context_constants_and_paths_initialized(
    mock_get_root, mock_paths_cls, mock_constants_cls
):
    """Test that DeploymentConstants and DeploymentPaths are initialized."""
    mock_get_root.return_value = Path("/test/project")
    mock_constants = Mock()
    mock_paths = Mock()
    mock_constants_cls.return_value = mock_constants
    mock_paths_cls.return_value = mock_paths

    ctx = build_cli_context()

    assert ctx.constants is mock_constants
    assert ctx.paths is mock_paths
    mock_constants_cls.assert_called_once_with()
    mock_paths_cls.assert_called_once_with(Path("/test/project"))
