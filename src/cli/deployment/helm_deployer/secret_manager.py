"""Secret management for Kubernetes deployments.

This module handles secret generation and deployment to Kubernetes,
including first-time setup with secret generation scripts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.cli.shared.console import CLIConsole
from src.infra.constants import DeploymentPaths

if TYPE_CHECKING:
    from rich.progress import Progress

    from ..shell_commands import ShellCommands


class SecretManager:
    """Manages Kubernetes secrets for deployment.

    Handles:
    - First-time secret generation (passwords, signing keys, certificates)
    - Deploying secrets to Kubernetes namespaces
    - Validating secret existence before deployment
    """

    def __init__(
        self,
        commands: ShellCommands,
        console: CLIConsole,
        paths: DeploymentPaths,
    ) -> None:
        """Initialize the secret manager.

        Args:
            commands: Shell command executor
            console: Rich console for output
            paths: Deployment path resolver
        """
        self.commands = commands
        self.console = console
        self.paths = paths

    def deploy_secrets(self, namespace: str, progress_factory: type[Progress]) -> None:
        """Generate (if needed) and deploy Kubernetes secrets.

        Args:
            namespace: Target Kubernetes namespace
            progress_factory: Rich Progress class for creating progress bars
        """
        self._generate_secrets_if_needed(progress_factory)

        self.console.print("[bold cyan]🔐 Deploying Kubernetes secrets...[/bold cyan]")

        script_path = self.paths.apply_secrets_script
        if not script_path.exists():
            from .image_builder import DeploymentError

            raise DeploymentError(
                "Cannot deploy secrets - script missing",
                details=(
                    f"Expected script at: {script_path}\n\n"
                    "This script is required to deploy secrets to Kubernetes.\n\n"
                    "Recovery steps:\n"
                    "  1. Check if the file was accidentally deleted\n"
                    "  2. Restore from git: git checkout -- infra/helm/api-forge/scripts/apply-secrets.sh\n"
                    "  3. Or regenerate project: uv run api-forge-cli init"
                ),
            )

        with progress_factory(transient=True) as progress:
            task = progress.add_task("Deploying secrets...", total=1)
            self.commands.run_bash_script(script_path, [namespace])
            progress.update(task, completed=1)

        self.console.print(
            f"[green]✓ Secrets deployed to namespace {namespace}[/green]"
        )

    def _generate_secrets_if_needed(self, progress_factory: type[Progress]) -> None:
        """Generate secrets if they don't exist (first-time setup)."""
        keys_dir = self.paths.secrets_keys_dir

        required_files = [
            keys_dir / "postgres_password.txt",
            keys_dir / "session_signing_secret.txt",
            keys_dir / "csrf_signing_secret.txt",
        ]

        if all(f.exists() for f in required_files):
            self.console.print("[dim]✓ Secrets already exist[/dim]")
            return

        self.console.print(
            "[bold yellow]🔑 Generating secrets (first time setup)...[/bold yellow]"
        )

        generate_script = self.paths.generate_secrets_script
        if not generate_script.exists():
            from .image_builder import DeploymentError

            self.console.print(
                f"[red]✗ Secret generation script not found: {generate_script}[/red]"
            )
            raise DeploymentError(
                "Cannot generate secrets - script missing",
                details=(
                    f"Expected script at: {generate_script}\n\n"
                    "This script generates required secrets for deployment:\n"
                    "  • PostgreSQL passwords\n"
                    "  • Session signing secrets\n"
                    "  • CSRF signing secrets\n"
                    "  • TLS certificates\n\n"
                    "Recovery steps:\n"
                    "  1. Check if the file was accidentally deleted\n"
                    "  2. Restore from git: git checkout -- infra/secrets/generate_secrets.sh\n"
                    "  3. Or regenerate project: uv run api-forge-cli init"
                ),
            )

        with progress_factory(transient=True) as progress:
            task = progress.add_task("Generating secrets and certificates...", total=1)
            self.commands.run_bash_script(generate_script)
            self.commands.run_bash_script(generate_script, ["--generate-pki"])
            progress.update(task, completed=1)

        self.console.print(
            "[green]✓ Secrets and certificates generated successfully[/green]"
        )
