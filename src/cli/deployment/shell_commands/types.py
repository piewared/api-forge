"""Data types for shell command results.

This module contains all dataclasses and type definitions used across
the shell command modules.

Note: CommandResult and ReplicaSetInfo are re-exported from src.infra.k8s.controller
for backward compatibility. New code should import directly from there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

# Re-export Kubernetes types from canonical location
from src.infra.k8s.controller import CommandResult, ReplicaSetInfo

__all__ = [
    "CommandResult",
    "ReplicaSetInfo",
    "HelmRelease",
    "GitStatus",
    "calculate_replicaset_age_hours",
]


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
