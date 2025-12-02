"""Data types for shell command results.

This module contains all dataclasses and type definitions used across
the shell command modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class CommandResult:
    """Result of a shell command execution.

    Attributes:
        success: Whether the command completed successfully (exit code 0)
        stdout: Standard output from the command
        stderr: Standard error from the command
        returncode: The exit code of the command
    """

    success: bool
    stdout: str
    stderr: str
    returncode: int


@dataclass
class HelmRelease:
    """Information about a Helm release.

    Attributes:
        name: Release name
        namespace: Kubernetes namespace
        status: Release status (deployed, failed, pending, uninstalling)
        revision: Release revision number
    """

    name: str
    namespace: str
    status: str
    revision: str


@dataclass
class ReplicaSetInfo:
    """Information about a Kubernetes ReplicaSet.

    Attributes:
        name: ReplicaSet name
        replicas: Desired replica count
        revision: Deployment revision annotation
        created_at: Creation timestamp
        owner_deployment: Name of the owning Deployment (if any)
    """

    name: str
    replicas: int
    revision: str
    created_at: datetime | None
    owner_deployment: str | None


@dataclass
class GitStatus:
    """Git repository status information.

    Attributes:
        is_git_repo: Whether the directory is a git repository
        is_clean: Whether the working tree has no uncommitted changes
        short_sha: Short commit SHA (7 chars) of HEAD, or None if not available
    """

    is_git_repo: bool
    is_clean: bool
    short_sha: str | None


def calculate_replicaset_age_hours(created_at: datetime | None) -> float | None:
    """Calculate the age of a ReplicaSet in hours.

    Args:
        created_at: Creation timestamp from ReplicaSetInfo

    Returns:
        Age in hours, or None if timestamp is invalid
    """
    if created_at is None:
        return None
    return (datetime.now(UTC) - created_at).total_seconds() / 3600
