"""Helm command abstractions.

This module provides commands for Helm release management,
including deployment, upgrades, uninstallation, and status queries.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .types import CommandResult, HelmRelease

if TYPE_CHECKING:
    from .runner import CommandRunner


class HelmCommands:
    """Helm-related shell commands.

    Provides operations for:
    - Release management (install, upgrade, uninstall)
    - Status queries (list releases, find stuck releases)
    """

    def __init__(self, runner: CommandRunner) -> None:
        """Initialize Helm commands.

        Args:
            runner: Command runner for executing shell commands
        """
        self._runner = runner

    # =========================================================================
    # Release Management
    # =========================================================================

    def upgrade_install(
        self,
        release_name: str,
        chart_path: Path,
        namespace: str,
        *,
        value_files: list[Path] | None = None,
        timeout: str = "10m",
        wait: bool = True,
        wait_for_jobs: bool = True,
        create_namespace: bool = True,
        on_output: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Deploy or upgrade a Helm release.

        Uses `helm upgrade --install` to idempotently deploy a chart.
        If the release doesn't exist, it will be installed. If it exists,
        it will be upgraded.

        Args:
            release_name: Name for the Helm release (e.g., "api-forge")
            chart_path: Path to the Helm chart directory
            namespace: Kubernetes namespace for deployment
            value_files: Optional list of values.yaml override files
            timeout: Maximum time to wait for deployment
            wait: Whether to wait for resources to be ready
            wait_for_jobs: Whether to wait for Jobs to complete
            create_namespace: Whether to create namespace if it doesn't exist
            on_output: Optional callback for real-time output streaming.
                      If provided, each line of output is passed to this function.

        Returns:
            CommandResult with deployment status

        Example:
            >>> helm.upgrade_install(
            ...     "my-app",
            ...     Path("./helm/my-app"),
            ...     "production",
            ...     value_files=[Path("./overrides.yaml")],
            ... )
        """
        cmd = [
            "helm",
            "upgrade",
            "--install",
            release_name,
            str(chart_path),
            "--namespace",
            namespace,
        ]

        if create_namespace:
            cmd.append("--create-namespace")
        if wait:
            cmd.append("--wait")
            cmd.append("--rollback-on-failure")  # Auto-rollback if pods fail
        if wait_for_jobs:
            cmd.append("--wait-for-jobs")
        cmd.extend(["--timeout", timeout])

        for vf in value_files or []:
            cmd.extend(["-f", str(vf)])

        # Use streaming if callback provided, otherwise capture output
        if on_output:
            return self._runner.run_streaming(cmd, on_output=on_output)
        return self._runner.run(cmd, capture_output=True)

    def uninstall(
        self,
        release_name: str,
        namespace: str,
        *,
        wait: bool = True,
    ) -> CommandResult:
        """Uninstall a Helm release.

        Args:
            release_name: Name of the release to uninstall
            namespace: Kubernetes namespace
            wait: Whether to wait for resources to be deleted

        Returns:
            CommandResult with uninstall status
        """
        cmd = ["helm", "uninstall", release_name, "-n", namespace]
        if wait:
            cmd.append("--wait")
        return self._runner.run(cmd)

    def rollback(
        self,
        release_name: str,
        namespace: str,
        revision: int | None = None,
        *,
        wait: bool = True,
        timeout: str = "5m",
    ) -> CommandResult:
        """Rollback a Helm release to a previous revision.

        Args:
            release_name: Name of the release to rollback
            namespace: Kubernetes namespace
            revision: Specific revision to rollback to (default: previous revision)
            wait: Whether to wait for rollback to complete
            timeout: Maximum time to wait for rollback

        Returns:
            CommandResult with rollback status
        """
        cmd = ["helm", "rollback", release_name, "-n", namespace]
        if revision is not None:
            cmd.append(str(revision))
        if wait:
            cmd.append("--wait")
        cmd.extend(["--timeout", timeout])
        return self._runner.run(cmd)

    def history(
        self,
        release_name: str,
        namespace: str,
        max_revisions: int = 10,
    ) -> list[dict[str, str]]:
        """Get release history.

        Args:
            release_name: Name of the release
            namespace: Kubernetes namespace
            max_revisions: Maximum number of revisions to return

        Returns:
            List of revision dictionaries with keys: revision, updated, status, description
        """
        cmd = [
            "helm",
            "history",
            release_name,
            "-n",
            namespace,
            "-o",
            "json",
            "--max",
            str(max_revisions),
        ]

        result = self._runner.run(cmd)
        if not result.success or not result.stdout:
            return []

        try:
            history_data: list[dict[str, str]] = json.loads(result.stdout)
            return history_data
        except json.JSONDecodeError:
            return []

    # =========================================================================
    # Status Queries
    # =========================================================================

    def list_releases(
        self,
        namespace: str,
        *,
        include_failed: bool = False,
        include_pending: bool = False,
        include_uninstalling: bool = False,
    ) -> list[HelmRelease]:
        """List Helm releases in a namespace.

        Args:
            namespace: Kubernetes namespace to query
            include_failed: Include releases in failed state
            include_pending: Include releases in pending state
            include_uninstalling: Include releases being uninstalled

        Returns:
            List of HelmRelease objects
        """
        cmd = ["helm", "list", "-n", namespace, "-o", "json"]
        if include_failed:
            cmd.append("--failed")
        if include_pending:
            cmd.append("--pending")
        if include_uninstalling:
            cmd.append("--uninstalling")

        result = self._runner.run(cmd)
        if not result.success or not result.stdout:
            return []

        try:
            releases_data = json.loads(result.stdout)
            return [
                HelmRelease(
                    name=r.get("name", ""),
                    namespace=r.get("namespace", ""),
                    status=r.get("status", ""),
                    revision=r.get("revision", ""),
                )
                for r in releases_data
            ]
        except json.JSONDecodeError:
            return []

    def get_stuck_releases(
        self,
        namespace: str,
        release_name: str | None = None,
    ) -> list[HelmRelease]:
        """Find Helm releases in problematic states.

        Args:
            namespace: Kubernetes namespace
            release_name: Optional filter for a specific release name

        Returns:
            List of releases in failed/pending/uninstalling states
        """
        cmd = [
            "helm",
            "list",
            "-n",
            namespace,
            "--uninstalling",
            "--pending",
            "--failed",
            "-o",
            "json",
        ]

        result = self._runner.run(cmd)
        if not result.success or not result.stdout:
            return []

        try:
            releases_data = json.loads(result.stdout)
            releases = [
                HelmRelease(
                    name=r.get("name", ""),
                    namespace=r.get("namespace", ""),
                    status=r.get("status", ""),
                    revision=r.get("revision", ""),
                )
                for r in releases_data
            ]
            if release_name:
                releases = [r for r in releases if r.name == release_name]
            return releases
        except json.JSONDecodeError:
            return []
