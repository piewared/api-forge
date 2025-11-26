"""Shared utilities for CLI commands."""

import subprocess
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

# Initialize Rich console for colored output
console = Console()


def get_project_root() -> Path:
    """Get the project root directory.

    Walks up from the module location to find the project root,
    identified by the presence of pyproject.toml.
    """
    current = Path(__file__).resolve()

    # Walk up the directory tree looking for pyproject.toml
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent

    # Fallback to three levels up (src/cli/utils.py -> project root)
    return Path(__file__).parent.parent.parent


def get_dev_dir() -> Path:
    """Get the dev_env directory (infrastructure and Docker files)."""
    project_root = get_project_root()
    return project_root / "docker" / "dev"


def run_command(
    command: list[str],
    cwd: Path | None = None,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[Any]:
    """Run a shell command with proper error handling."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd or get_project_root(),
            check=check,
            capture_output=capture_output,
            text=True,
        )
        return result
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Command failed: {' '.join(command)}[/red]")
        console.print(f"[red]Exit code: {e.returncode}[/red]")
        if e.stdout:
            console.print(f"[red]stdout: {e.stdout}[/red]")
        if e.stderr:
            console.print(f"[red]stderr: {e.stderr}[/red]")
        raise typer.Exit(1) from e
