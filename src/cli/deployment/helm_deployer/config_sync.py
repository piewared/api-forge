"""Configuration synchronization between config.yaml and Helm values.yaml.

This module handles copying configuration files to the Helm staging area
and synchronizing settings between the application config and Helm values.

Uses ruamel.yaml for YAML editing to preserve comments, ordering, and formatting
when round-tripping YAML files.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from ruamel.yaml import YAML

from src.app.runtime.config.config_loader import load_config
from src.cli.shared.console import CLIConsole
from src.infra.constants import DeploymentPaths

if TYPE_CHECKING:
    from rich.progress import Progress


class ConfigSynchronizer:
    """Synchronizes configuration between config.yaml and Helm values.yaml.

    Handles:
    - Syncing service enable/disable flags (redis.enabled, temporal.enabled)
    - Copying config files to Helm staging area
    - Ensuring consistency between application and deployment configuration
    """

    def __init__(
        self,
        console: CLIConsole,
        paths: DeploymentPaths,
    ) -> None:
        """Initialize the config synchronizer.

        Args:
            console: Rich console for output
            paths: Deployment path resolver
        """
        self.console = console
        self.paths = paths

    def sync_config_to_values(self) -> None:
        """Synchronize config.yaml settings to Helm values.yaml.

        Ensures service enable/disable flags are consistent between
        application config and Helm deployment values.
        """
        self.console.print(
            "[bold cyan]🔄 Synchronizing config.yaml → values.yaml...[/bold cyan]"
        )

        config_path = self.paths.config_yaml
        values_path = self.paths.values_yaml

        if not config_path.exists():
            self.console.warn("config.yaml not found, skipping sync")
            return

        try:
            changes = self._compute_config_changes(config_path, values_path)
            if changes:
                self.console.ok("Synced changes:")
                for change in changes:
                    self.console.print(f"  • {change}")
            else:
                self.console.print(
                    "[dim]  ✓ No changes needed (values already in sync)[/dim]"
                )
        except Exception as e:
            self.console.warn(f"Failed to sync config: {e}")
            self.console.print("[dim]  Continuing with existing values.yaml[/dim]")

    def _compute_config_changes(
        self,
        config_path: Path,
        values_path: Path,
    ) -> list[str]:
        """Compare and update values.yaml with config.yaml settings.

        Uses ruamel.yaml to preserve comments and formatting in values.yaml.

        Args:
            config_path: Path to config.yaml
            values_path: Path to values.yaml

        Returns:
            List of change descriptions (empty if no changes)
        """
        config_raw = load_config(config_path, processed=False)
        config_data = config_raw if isinstance(config_raw, dict) else {}

        # Set up ruamel.yaml for round-trip (comment-preserving) mode
        yaml = YAML()
        yaml.preserve_quotes = True

        # Read values.yaml for comparison (to detect what needs changing)
        with open(values_path) as f:
            values_data = yaml.load(f)

        changes = []
        modified = False

        # Check redis.enabled
        if redis_config := config_data.get("config", {}).get("redis"):
            if "redis" in values_data:
                old_val = values_data["redis"].get("enabled", True)
                new_val = redis_config.get("enabled", True)
                if old_val != new_val:
                    values_data["redis"]["enabled"] = new_val
                    changes.append(f"redis.enabled: {old_val} → {new_val}")
                    modified = True

        # Check temporal.enabled
        if temporal_config := config_data.get("config", {}).get("temporal"):
            if "temporal" in values_data:
                old_val = values_data["temporal"].get("enabled", True)
                new_val = temporal_config.get("enabled", True)
                if old_val != new_val:
                    values_data["temporal"]["enabled"] = new_val
                    changes.append(f"temporal.enabled: {old_val} → {new_val}")
                    modified = True

        # Check postgres.enabled
        if database_config := config_data.get("config", {}).get("database"):
            if "bundled_postgres" in database_config:
                if "postgres" in values_data:
                    old_val = values_data["postgres"].get("enabled", True)
                    new_val = database_config["bundled_postgres"].get("enabled", True)
                    if old_val != new_val:
                        values_data["postgres"]["enabled"] = new_val
                        changes.append(f"postgres.enabled: {old_val} → {new_val}")
                        modified = True

        # Write back with preserved formatting if any changes were made
        if modified:
            with open(values_path, "w") as f:
                yaml.dump(values_data, f)

        return changes

    def copy_config_files(self, progress_factory: type[Progress]) -> None:
        """Copy configuration files to Helm staging area.

        Copies .env, config.yaml, PostgreSQL configs, Temporal scripts,
        and entrypoint scripts to infra/helm/api-forge/files/ and
        infra/helm/api-forge-bundled-postgres/files/.

        Args:
            progress_factory: Rich Progress class for creating progress bars
        """
        self.console.print(
            "[bold cyan]📋 Copying config files to Helm staging area...[/bold cyan]"
        )

        # Prepare both destination directories
        self.paths.helm_files.mkdir(parents=True, exist_ok=True)
        bundled_postgres_files = self.paths.postgres_standalone_chart / "files"
        bundled_postgres_files.mkdir(parents=True, exist_ok=True)

        files_to_copy = self._get_config_files_manifest()

        with progress_factory(transient=True) as progress:
            task = progress.add_task("Copying files...", total=len(files_to_copy))

            for source, dest_name, description in files_to_copy:
                if source.exists():
                    # Copy to main api-forge chart
                    dest_path = self.paths.helm_files / dest_name
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest_path)

                    # Also copy to bundled-postgres chart
                    bundled_dest_path = bundled_postgres_files / dest_name
                    bundled_dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, bundled_dest_path)

                    self.console.print(f"  [dim]✓ {description}[/dim]")
                else:
                    self.console.warn(f"  Skipped {description} (not found)")
                progress.update(task, advance=1)

        rel_path = self.paths.helm_files.relative_to(self.paths.project_root)
        bundled_rel_path = bundled_postgres_files.relative_to(self.paths.project_root)
        self.console.ok(f"Config files copied to {rel_path}")
        self.console.ok(f"Config files copied to {bundled_rel_path}")

    def _get_config_files_manifest(self) -> list[tuple[Path, str, str]]:
        """Get list of config files to copy to Helm staging.

        Returns:
            List of (source_path, dest_name, description) tuples
        """
        pg_dir = self.paths.docker_prod / "postgres"
        temporal_dir = self.paths.docker_prod / "temporal" / "scripts"

        return [
            # Core config files
            (self.paths.env_file, ".env", "Environment variables"),
            (self.paths.config_yaml, "config.yaml", "Application config"),
            # PostgreSQL configs
            (pg_dir / "postgresql.conf", "postgresql.conf", "PostgreSQL config"),
            (pg_dir / "pg_hba.conf", "pg_hba.conf", "PostgreSQL HBA config"),
            (pg_dir / "verify-init.sh", "verify-init.sh", "PostgreSQL verifier script"),
            (
                pg_dir / "init-scripts" / "01-init-app.sh",
                "01-init-app.sh",
                "PostgreSQL init script",
            ),
            # Universal entrypoint
            (
                self.paths.docker_prod / "scripts" / "universal-entrypoint.sh",
                "universal-entrypoint.sh",
                "Universal entrypoint",
            ),
            # Temporal scripts
            (
                temporal_dir / "schema-setup.sh",
                "temporal/schema-setup.sh",
                "Temporal schema setup",
            ),
            (
                temporal_dir / "entrypoint.sh",
                "temporal/entrypoint.sh",
                "Temporal entrypoint",
            ),
            (
                temporal_dir / "namespace-init.sh",
                "temporal/namespace-init.sh",
                "Temporal namespace init",
            ),
        ]
