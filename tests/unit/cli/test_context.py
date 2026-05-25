"""Tests for CLI context dependency injection.

``CLIContext`` is a frozen dataclass whose field set depends on the
``include_k8s_deploy`` toggle (the k8s build adds a ``k8s_controller``
field; the non-k8s build omits it entirely). To keep this file a single
source of truth across both shapes:

- Construction helpers use ``dataclasses.fields(CLIContext)`` to pick up
  whatever the current build's field set is, so adding/removing
  toggle-conditional fields doesn't require touching tests here.
- The conditional ``get_k8s_controller_sync`` patch is applied via
  ``_build_cli_context_patches()``, which is a no-op in the non-k8s build
  (where that symbol doesn't exist to patch).
"""

from contextlib import ExitStack, contextmanager
from dataclasses import fields
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
import typer

import src.cli.context as _context_module
from src.cli.context import CLIContext, build_cli_context, get_cli_context

# True iff the k8s subtree is present in this build — the source module only
# imports ``get_k8s_controller_sync`` under the ``include_k8s_deploy`` jinja
# guard, so its presence is the canonical signal.
_HAS_K8S = hasattr(_context_module, "get_k8s_controller_sync")


def _ctx_kwargs(**overrides: Any) -> dict[str, Any]:
    """Build kwargs for ``CLIContext`` covering every declared field with a
    Mock default. Toggle-conditional fields (e.g. ``k8s_controller``) are
    picked up automatically via dataclass introspection."""
    base: dict[str, Any] = {
        "console": Mock(),
        "project_root": Path("/test"),
        "commands": Mock(),
        "constants": Mock(),
        "paths": Mock(),
    }
    for field in fields(CLIContext):
        base.setdefault(field.name, Mock())
    base.update(overrides)
    return base


@contextmanager
def _build_cli_context_patches():
    """Patch the external deps ``build_cli_context`` reaches for. No-op for
    the non-k8s build, where ``get_k8s_controller_sync`` isn't imported."""
    with ExitStack() as stack:
        if _HAS_K8S:
            mock_k8s = stack.enter_context(
                patch("src.cli.context.get_k8s_controller_sync")
            )
            mock_k8s.return_value = Mock()
        yield


def test_cli_context_is_immutable():
    ctx = CLIContext(**_ctx_kwargs())

    with pytest.raises(AttributeError):
        ctx.console = Mock()  # type: ignore[attr-defined]


@patch("src.cli.context.get_project_root")
def test_build_cli_context_creates_all_dependencies(mock_get_root):
    """Every declared field on CLIContext is populated (non-None) after
    ``build_cli_context()``. Iterating ``fields(CLIContext)`` keeps the
    assertion in sync with the toggle-conditional dataclass shape."""
    mock_get_root.return_value = Path("/test/project")

    with _build_cli_context_patches():
        ctx = build_cli_context()

    for field in fields(CLIContext):
        assert getattr(ctx, field.name) is not None, f"{field.name} not populated"
    assert ctx.project_root == Path("/test/project")


@patch("src.cli.context.get_project_root")
def test_build_cli_context_paths_uses_project_root(mock_get_root):
    """Test that DeploymentPaths is initialized with project root."""
    mock_get_root.return_value = Path("/test/project")

    with _build_cli_context_patches():
        ctx = build_cli_context()

    assert hasattr(ctx.paths, "project_root")


def test_get_cli_context_from_typer_context():
    """Test that get_cli_context retrieves from Typer context."""
    mock_ctx_obj = CLIContext(**_ctx_kwargs())

    typer_ctx = Mock(spec=typer.Context)
    typer_ctx.obj = mock_ctx_obj

    result = get_cli_context(typer_ctx)

    assert result is mock_ctx_obj


def test_get_cli_context_with_none_raises_outside_typer_command():
    """get_cli_context must NOT silently build a real CLIContext when no typer
    context is attached — that would spin up the k8s controller, shell
    commands, etc. as a side effect of imports during tests."""
    with patch("click.get_current_context", return_value=None):
        with pytest.raises(RuntimeError, match="CLIContext is not configured"):
            get_cli_context(None)


def test_get_cli_context_with_invalid_obj_raises():
    """A typer ctx whose obj isn't a CLIContext must raise rather than build
    a fresh one (same rationale as the no-ctx case)."""
    typer_ctx = Mock(spec=typer.Context)
    typer_ctx.obj = "invalid"  # Not a CLIContext

    with patch("click.get_current_context", return_value=None):
        with pytest.raises(RuntimeError, match="CLIContext is not configured"):
            get_cli_context(typer_ctx)


@patch("click.get_current_context")
def test_get_cli_context_uses_click_context_as_fallback(mock_get_click_ctx):
    """Test that get_cli_context uses click context when typer ctx is None."""
    mock_ctx_obj = CLIContext(**_ctx_kwargs())

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

    with _build_cli_context_patches():
        build_cli_context()

    mock_shell_commands.assert_called_once_with(Path("/test/project"))


def test_cli_context_all_fields_accessible():
    """Every declared field is accessible after construction. Iterates
    ``fields(CLIContext)`` so the assertion stays correct when the
    toggle-conditional field set changes."""
    ctx = CLIContext(**_ctx_kwargs())

    for field in fields(CLIContext):
        assert getattr(ctx, field.name) is not None, f"{field.name} not accessible"
    assert ctx.project_root == Path("/test")


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

    with _build_cli_context_patches():
        ctx = build_cli_context()

    assert ctx.constants is mock_constants
    assert ctx.paths is mock_paths
    mock_constants_cls.assert_called_once_with()
    mock_paths_cls.assert_called_once_with(Path("/test/project"))
