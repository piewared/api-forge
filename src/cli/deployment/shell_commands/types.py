"""Data types for shell command results.

This module contains all dataclasses and type definitions used across
the shell command modules.

``CommandResult`` and ``ReplicaSetInfo`` were historically re-exported
here from ``src.infra.k8s.controller`` for backward compatibility. The
re-export is gated on the k8s subtree being present so projects
generated with ``include_k8s_deploy=false`` can still import this
module — those projects only ever exercise dev/prod paths that don't
need either type at runtime. New code should import the k8s types
directly from their canonical location.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

try:
    from src.infra.k8s.controller import CommandResult, ReplicaSetInfo
except ModuleNotFoundError:
    # k8s subtree excluded by the template toggle. The names are still
    # available as opaque ``Any``s so downstream type hints don't break.
    from typing import Any as CommandResult  # type: ignore[assignment]
    from typing import Any as ReplicaSetInfo  # type: ignore[assignment]

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
