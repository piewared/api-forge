"""Configuration synchronization between config.yaml and Helm values.yaml.

This module handles copying configuration files to the Helm staging area
and synchronizing settings between the application config and Helm values.

Note on YAML editing:
    This module uses regex-based line editing to preserve comments and structure
    in values.yaml. If more complex YAML manipulation is needed in the future,
    consider using `ruamel.yaml` instead of `pyyaml`. ruamel.yaml preserves
    comments, ordering, and formatting when round-tripping YAML files:

        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.preserve_quotes = True
        with open(path) as f:
            data = yaml.load(f)
        # modify data...
        with open(path, 'w') as f:
            yaml.dump(data, f)
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import yaml  # type: ignore[import-untyped]

from src.app.runtime.config.config_loader import load_config

from .constants import DeploymentPaths

if TYPE_CHECKING:
    from rich.console import Console
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
        console: Console,
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
            self.console.print(
                "[yellow]⚠️  config.yaml not found, skipping sync[/yellow]"
            )
            return

        try:
            changes = self._compute_config_changes(config_path, values_path)
            if changes:
                self.console.print("[green]✓ Synced changes:[/green]")
                for change in changes:
                    self.console.print(f"  • {change}")
            else:
                self.console.print(
                    "[dim]  ✓ No changes needed (values already in sync)[/dim]"
                )
        except Exception as e:
            self.console.print(f"[yellow]⚠️  Failed to sync config: {e}[/yellow]")
            self.console.print("[dim]  Continuing with existing values.yaml[/dim]")

    def _compute_config_changes(
        self,
        config_path: Path,
        values_path: Path,
    ) -> list[str]:
        """Compare and update values.yaml with config.yaml settings.

        Uses line-based editing to preserve comments and formatting in values.yaml.

        Args:
            config_path: Path to config.yaml
            values_path: Path to values.yaml

        Returns:
            List of change descriptions (empty if no changes)
        """
        config_raw = load_config(config_path, processed=False)
        config_data = config_raw if isinstance(config_raw, dict) else {}

        # Read values.yaml for comparison (to detect what needs changing)
        with open(values_path) as f:
            values_data = yaml.safe_load(f)

        changes = []
        updates: dict[str, tuple[bool, bool]] = {}  # key -> (old_val, new_val)

        # Check redis.enabled
        if redis_config := config_data.get("config", {}).get("redis"):
            if "redis" in values_data:
                old_val = values_data["redis"].get("enabled", True)
                new_val = redis_config.get("enabled", True)
                if old_val != new_val:
                    updates["redis"] = (old_val, new_val)
                    changes.append(f"redis.enabled: {old_val} → {new_val}")

        # Check temporal.enabled
        if temporal_config := config_data.get("config", {}).get("temporal"):
            if "temporal" in values_data:
                old_val = values_data["temporal"].get("enabled", True)
                new_val = temporal_config.get("enabled", True)
                if old_val != new_val:
                    updates["temporal"] = (old_val, new_val)
                    changes.append(f"temporal.enabled: {old_val} → {new_val}")

        if updates:
            self._update_values_preserving_format(values_path, updates)

        return changes

    def _update_values_preserving_format(
        self,
        values_path: Path,
        updates: dict[str, tuple[bool, bool]],
    ) -> None:
        """Update values.yaml while preserving comments and formatting.

        Uses line-based editing to find and update specific values without
        rewriting the entire file.

        Args:
            values_path: Path to values.yaml
            updates: Dict of section_name -> (old_value, new_value) to update
        """
        with open(values_path) as f:
            lines = f.readlines()

        current_section: str | None = None
        modified_lines = []

        for line in lines:
            # Detect top-level section (no leading whitespace, ends with :)
            stripped = line.rstrip()
            if stripped and not line[0].isspace() and stripped.endswith(":"):
                # Extract section name (e.g., "redis:" -> "redis")
                current_section = stripped[:-1].split("#")[0].strip()

            # Check if this line is an 'enabled:' setting in a section we want to update
            if current_section in updates:
                # Match lines like "  enabled: true" or "  enabled: false"
                match = re.match(r"^(\s+enabled:\s*)(true|false)(.*)$", line)
                if match:
                    indent, old_bool, rest = match.groups()
                    _, new_val = updates[current_section]
                    new_bool = "true" if new_val else "false"
                    line = f"{indent}{new_bool}{rest}\n"

            modified_lines.append(line)

        with open(values_path, "w") as f:
            f.writelines(modified_lines)

    def copy_config_files(self, progress_factory: type[Progress]) -> None:
        """Copy configuration files to Helm staging area.

        Copies .env, config.yaml, PostgreSQL configs, Temporal scripts,
        and entrypoint scripts to infra/helm/api-forge/files/.

        Args:
            progress_factory: Rich Progress class for creating progress bars
        """
        self.console.print(
            "[bold cyan]📋 Copying config files to Helm staging area...[/bold cyan]"
        )

        self.paths.helm_files.mkdir(parents=True, exist_ok=True)

        files_to_copy = self._get_config_files_manifest()

        with progress_factory(transient=True) as progress:
            task = progress.add_task("Copying files...", total=len(files_to_copy))

            for source, dest_name, description in files_to_copy:
                if source.exists():
                    dest_path = self.paths.helm_files / dest_name
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest_path)
                    self.console.print(f"  [dim]✓ {description}[/dim]")
                else:
                    self.console.print(
                        f"  [yellow]⚠ Skipped {description} (not found)[/yellow]"
                    )
                progress.update(task, advance=1)

        rel_path = self.paths.helm_files.relative_to(self.paths.project_root)
        self.console.print(f"[green]✓ Config files copied to {rel_path}[/green]")

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
