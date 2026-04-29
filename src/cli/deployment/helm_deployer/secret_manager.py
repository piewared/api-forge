"""Secret management for Kubernetes deployments.

This module handles secret generation and deployment to Kubernetes,
including first-time setup with secret generation scripts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.cli.prompts import ConsolePromptProvider
from src.cli.shared.console import CLIConsole
from src.infra.constants import DeploymentPaths
from src.infra.secrets import (
    GeneratorConfig,
    PKICertificateGenerator,
    SecretGenerationOrchestrator,
    SecretKind,
    get_secrets_manager,
)

if TYPE_CHECKING:
    from rich.progress import Progress

    from ..shell_commands import ShellCommands


class HelmDeploymentSecretManager:
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
        self._generate_secrets_if_needed()

        self.console.info("Deploying Kubernetes secrets...")

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

        self.console.ok(f"Secrets deployed to namespace {namespace}")

    def _generate_secrets_if_needed(self) -> None:
        """Generate secrets if they don't exist (first-time setup)."""
        manager = get_secrets_manager()

        # Check if key secrets exist
        required_keys = [
            "postgres_password",
            "session_signing_secret",
            "csrf_signing_secret",
        ]

        # Check if PKI certificates exist
        required_certs = [
            "root-ca.crt",
            "root-ca.key",
        ]

        keys_exist = all(manager.exists(key) for key in required_keys)
        certs_exist = all(
            manager.exists(cert, SecretKind.CERT) for cert in required_certs
        )

        if keys_exist and certs_exist:
            self.console.ok("Secrets and certificates already exist")
            return

        self.console.info("Generating secrets and certificates (first time setup)...")

        # Create generator config
        config = GeneratorConfig(
            secrets_manager=manager,
            prompt_provider=ConsolePromptProvider(self.console.console),
            non_interactive=False,
            overwrite_secrets=False,
        )

        # Generate secrets
        orchestrator = SecretGenerationOrchestrator(
            config=config,
            console=self.console,
        )
        orchestrator.generate_all_secrets()

        # Generate PKI certificates
        self.console.info("Generating PKI certificates...")
        pki_generator = PKICertificateGenerator(manager)
        pki_generator.generate_pki_certificates()

        self.console.ok("Secrets and certificates generated successfully")
