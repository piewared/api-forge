"""Post-deployment cleanup operations.

This module handles cleanup of old Kubernetes resources after deployment,
including scaling down and deleting old ReplicaSets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..shell_commands import ReplicaSetInfo, calculate_replicaset_age_hours
from .constants import DeploymentConstants

if TYPE_CHECKING:
    from rich.console import Console

    from ..shell_commands import ShellCommands


class CleanupManager:
    """Manages post-deployment cleanup operations.

    Handles:
    - Scaling down old ReplicaSets to 0 replicas
    - Deleting old ReplicaSets beyond age threshold
    - Resource cleanup for stale deployments
    """

    def __init__(
        self,
        commands: ShellCommands,
        console: Console,
        constants: DeploymentConstants | None = None,
    ) -> None:
        """Initialize the cleanup manager.

        Args:
            commands: Shell command executor
            console: Rich console for output
            constants: Optional deployment constants
        """
        self.commands = commands
        self.console = console
        self.constants = constants or DeploymentConstants()

    def scale_down_old_replicasets(self, namespace: str) -> None:
        """Scale down old ReplicaSets to 0 replicas.

        After a deployment restart, old ReplicaSets may still have replicas.
        This ensures they're immediately scaled to 0.

        Args:
            namespace: Target Kubernetes namespace
        """
        try:
            replicasets = self.commands.kubectl.get_replicasets(namespace)
            scaled_count = 0

            for rs in replicasets:
                if not self._should_scale_down_replicaset(rs, namespace):
                    continue

                self.commands.kubectl.scale_replicaset(rs.name, namespace, 0)
                scaled_count += 1

            if scaled_count > 0:
                self.console.print(
                    f"[dim]✓ Scaled down {scaled_count} old ReplicaSet(s)[/dim]"
                )

        except Exception as e:
            self.console.print(
                f"[dim yellow]⚠️  Could not scale down old ReplicaSets: {e}[/dim yellow]"
            )

    def _should_scale_down_replicaset(self, rs: ReplicaSetInfo, namespace: str) -> bool:
        """Determine if a ReplicaSet should be scaled down.

        Args:
            rs: ReplicaSetInfo object
            namespace: Kubernetes namespace

        Returns:
            True if the ReplicaSet is old and should be scaled down
        """
        # Only process app/worker ReplicaSets with running pods
        if not rs.name.startswith(self.constants.DEPLOYMENT_PREFIXES):
            return False
        if rs.replicas == 0:
            return False
        if not rs.owner_deployment:
            return False

        # Check if this is an old revision
        current_revision = self.commands.kubectl.get_deployment_revision(
            rs.owner_deployment, namespace
        )
        return bool(rs.revision) and rs.revision != current_revision

    def cleanup_old_replicasets(self, namespace: str) -> None:
        """Clean up old ReplicaSets beyond age threshold.

        Kubernetes manages ReplicaSet retention via revisionHistoryLimit,
        but this cleans up very old ones (>1 hour with 0 replicas).

        Args:
            namespace: Target Kubernetes namespace
        """
        self.console.print("[bold cyan]🧹 Cleaning up old ReplicaSets...[/bold cyan]")

        try:
            replicasets = self.commands.kubectl.get_replicasets(namespace)
            deleted_count = 0

            for rs in replicasets:
                if not self._should_delete_replicaset(rs):
                    continue

                self.commands.kubectl.delete_replicaset(rs.name, namespace)
                deleted_count += 1

            if deleted_count > 0:
                self.console.print(
                    f"[green]✓ Cleaned up {deleted_count} old ReplicaSet(s)[/green]"
                )
            else:
                self.console.print("[dim]No old ReplicaSets to clean up[/dim]")

        except Exception as e:
            self.console.print(
                f"[yellow]⚠ Failed to clean up old ReplicaSets: {e}[/yellow]"
            )

    def _should_delete_replicaset(self, rs: ReplicaSetInfo) -> bool:
        """Determine if a ReplicaSet should be deleted.

        Args:
            rs: ReplicaSetInfo object

        Returns:
            True if the ReplicaSet is old enough to delete
        """
        # Only delete app/worker ReplicaSets with 0 replicas
        if not rs.name.startswith(self.constants.DEPLOYMENT_PREFIXES):
            return False
        if rs.replicas != 0:
            return False

        # Only delete if older than threshold
        age_hours = calculate_replicaset_age_hours(rs.created_at)
        return (
            age_hours is not None
            and age_hours > self.constants.REPLICASET_AGE_THRESHOLD_HOURS
        )
