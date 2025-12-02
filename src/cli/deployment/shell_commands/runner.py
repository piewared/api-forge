"""Command runner for executing shell commands.

This module provides the base command execution functionality used by
all specialized command modules.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from .types import CommandResult


class CommandRunner:
    """Low-level command executor with consistent result handling.

    This class provides the foundation for executing shell commands with
    proper output capture, error handling, and streaming support.

    All specialized command modules (Docker, Helm, kubectl, etc.) use
    this runner for actual command execution.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialize the command runner.

        Args:
            project_root: Path to the project root directory.
                         Commands will be executed from this directory by default.
        """
        self.project_root = project_root

    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path | None = None,
        capture_output: bool = True,
        check: bool = False,
    ) -> CommandResult:
        """Execute a shell command and return structured result.

        Args:
            cmd: Command and arguments as a sequence
            cwd: Working directory (defaults to project_root)
            capture_output: Whether to capture stdout/stderr
            check: Whether to raise exception on non-zero exit code

        Returns:
            CommandResult with success status, output, and return code

        Raises:
            subprocess.CalledProcessError: If check=True and command fails
        """
        result = subprocess.run(
            list(cmd),
            cwd=cwd or self.project_root,
            capture_output=capture_output,
            text=True,
            check=check,
        )
        return CommandResult(
            success=result.returncode == 0,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            returncode=result.returncode,
        )

    def run_streaming(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Execute a shell command with real-time output streaming.

        This method runs a command and calls the on_output callback for each
        line of output, allowing real-time progress display.

        Args:
            cmd: Command and arguments as a sequence
            cwd: Working directory (defaults to project_root)
            on_output: Callback function called with each line of output.
                      If None, output is collected but not streamed.

        Returns:
            CommandResult with success status, collected output, and return code
        """
        # Set environment to disable output buffering
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        process = subprocess.Popen(
            list(cmd),
            cwd=cwd or self.project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            text=True,
            bufsize=0,  # Unbuffered
            env=env,
        )

        stdout_lines: list[str] = []

        # Read output line by line
        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                line = line.rstrip("\n")
                if line:  # Only process non-empty lines
                    stdout_lines.append(line)
                    if on_output:
                        on_output(line)

        process.wait()

        return CommandResult(
            success=process.returncode == 0,
            stdout="\n".join(stdout_lines),
            stderr="",  # stderr is merged into stdout
            returncode=process.returncode or 0,
        )

    def run_checked(
        self,
        cmd: Sequence[str],
        *,
        cwd: Path | None = None,
        capture_output: bool = True,
    ) -> str:
        """Execute a command and return stdout, raising on failure.

        Args:
            cmd: Command and arguments
            cwd: Working directory (defaults to project_root)
            capture_output: Whether to capture stdout/stderr

        Returns:
            Standard output from the command

        Raises:
            subprocess.CalledProcessError: If command exits with non-zero code
        """
        result = self.run(cmd, cwd=cwd, capture_output=capture_output, check=True)
        return result.stdout
