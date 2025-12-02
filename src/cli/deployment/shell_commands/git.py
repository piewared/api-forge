"""Git command abstractions.

This module provides commands for Git repository operations,
primarily used for determining content-based image tags.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .types import GitStatus

if TYPE_CHECKING:
    from .runner import CommandRunner


class GitCommands:
    """Git-related shell commands.

    Provides operations for:
    - Repository status detection
    - Commit SHA retrieval
    - Working tree cleanliness checks
    """

    def __init__(self, runner: CommandRunner) -> None:
        """Initialize Git commands.

        Args:
            runner: Command runner for executing shell commands
        """
        self._runner = runner

    def get_status(self) -> GitStatus:
        """Get the current git repository status.

        Checks if the current directory is a git repository, whether
        there are uncommitted changes, and retrieves the current commit SHA.

        Returns:
            GitStatus with repository state information

        Example:
            >>> status = git.get_status()
            >>> if status.is_clean:
            ...     print(f"Clean repo at {status.short_sha}")
        """
        # Check for uncommitted changes
        status_result = self._runner.run(["git", "status", "--porcelain"])
        if not status_result.success:
            return GitStatus(is_git_repo=False, is_clean=False, short_sha=None)

        is_clean = not bool(status_result.stdout.strip())

        # Get short SHA
        sha_result = self._runner.run(["git", "rev-parse", "--short=7", "HEAD"])
        short_sha = sha_result.stdout.strip() if sha_result.success else None

        return GitStatus(is_git_repo=True, is_clean=is_clean, short_sha=short_sha)
