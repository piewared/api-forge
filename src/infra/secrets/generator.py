"""Secret generation orchestration.

This module provides the SecretGenerationOrchestrator which coordinates
secret generation using the SecretsManager abstraction for storage.

For low-level cryptographic primitives, see the crypto module.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .base import SecretKind, SecretsManager
from .crypto import SecretGenerator
from .file_manager import FileSecretsManager


class SecretType(Enum):
    """Types of secrets that can be generated."""

    POSTGRES_PASSWORD = "postgres_password"
    POSTGRES_APP_USER_PW = "postgres_app_user_pw"
    POSTGRES_APP_RO_PW = "postgres_app_ro_pw"
    POSTGRES_APP_OWNER_PW = "postgres_app_owner_pw"
    POSTGRES_TEMPORAL_PW = "postgres_temporal_pw"
    REDIS_PASSWORD = "redis_password"
    SESSION_SIGNING_SECRET = "session_signing_secret"
    CSRF_SIGNING_SECRET = "csrf_signing_secret"
    OIDC_GOOGLE_CLIENT_SECRET = "oidc_google_client_secret"
    OIDC_MICROSOFT_CLIENT_SECRET = "oidc_microsoft_client_secret"
    OIDC_KEYCLOAK_CLIENT_SECRET = "oidc_keycloak_client_secret"


# Minimum required lengths for each secret type
SECRET_MIN_LENGTHS: dict[SecretType, int] = {
    SecretType.POSTGRES_PASSWORD: 24,
    SecretType.POSTGRES_APP_USER_PW: 24,
    SecretType.POSTGRES_APP_RO_PW: 24,
    SecretType.POSTGRES_APP_OWNER_PW: 24,
    SecretType.POSTGRES_TEMPORAL_PW: 24,
    SecretType.REDIS_PASSWORD: 16,
    SecretType.SESSION_SIGNING_SECRET: 32,
    SecretType.CSRF_SIGNING_SECRET: 32,
    SecretType.OIDC_GOOGLE_CLIENT_SECRET: 32,
    SecretType.OIDC_MICROSOFT_CLIENT_SECRET: 32,
    SecretType.OIDC_KEYCLOAK_CLIENT_SECRET: 32,
}


class PromptProvider(Protocol):
    """Protocol for prompting user input."""

    def prompt_for_secret(self, message: str) -> str:
        """Prompt user for a secret value."""
        ...

    def confirm(self, message: str) -> bool:
        """Prompt user for yes/no confirmation."""
        ...


@dataclass
class GeneratorConfig:
    """Configuration for secret/certificate generation."""

    secrets_manager: SecretsManager | None = None
    """SecretsManager instance for storage operations. If None, uses FileSecretsManager."""

    secrets_dir: Path | None = None
    """Base secrets directory (for FileSecretsManager if secrets_manager is None)."""

    non_interactive: bool = False
    overwrite_secrets: bool = False

    prompt_provider: PromptProvider | None = None
    """Provider for interactive prompts. Required if non_interactive is False."""

    user_secrets_file: Path | None = None
    # CLI-provided OIDC secrets
    oidc_google_secret: str | None = None
    oidc_microsoft_secret: str | None = None
    oidc_keycloak_secret: str | None = None

    def get_secrets_manager(self) -> SecretsManager:
        """Get the configured secrets manager, creating a default if needed."""
        if self.secrets_manager is not None:
            return self.secrets_manager
        # Create FileSecretsManager with configured paths
        if self.secrets_dir:
            return FileSecretsManager(
                secrets_dir=self.secrets_dir / "keys",
                certs_dir=self.secrets_dir / "certs",
                backups_dir=self.secrets_dir / "backups",
            )
        return FileSecretsManager()


class ConsoleProtocol(Protocol):
    """Protocol for console output."""

    def print(self, msg: Any = None) -> None:
        """Print to the console."""
        ...

    def status(self, status: str) -> Any:
        """Show a status spinner."""
        ...

    def info(self, msg: str) -> None:
        """Print an info message."""
        ...

    def ok(self, msg: str) -> None:
        """Print a success message."""
        ...

    def error(self, msg: str) -> None:
        """Print an error message."""
        ...

    def warn(self, msg: str) -> None:
        """Print a warning message."""
        ...


class SecretGenerationOrchestrator:
    """Orchestrator for secret generation and management.

    Coordinates the generation of secrets using a SecretsManager for storage.
    This class handles the generation logic (prompts, validation, etc.) while
    delegating actual storage to the SecretsManager abstraction.
    """

    def __init__(
        self,
        config: GeneratorConfig,
        console: ConsoleProtocol | None = None,
    ):
        self.config = config
        self.console = console  # Use the passed console (likely CLIConsole or Rich)

        # Validation
        if not self.config.non_interactive and not self.config.prompt_provider:
            raise ValueError("PromptProvider is required when non_interactive is False")

        self.prompt_provider = self.config.prompt_provider

        # If no console or prompt provider is available, we might default to
        # standard IO if needed, but for now we rely on injection.
        # This keeps the infra layer free of direct Rich dependencies except
        # for type checking.

        self.user_secrets_loaded = False
        self.user_secrets: dict[str, str] = {}
        self._secrets_manager = config.get_secrets_manager()

    def load_user_supplied_secrets(self) -> None:
        """Load user-supplied secrets from file."""
        if self.config.user_secrets_file is None:
            return

        # We assume self.console has a .print method

        if not self.config.user_secrets_file.exists():
            if self.console:
                self.console.warn(
                    f"User secrets file not found: {self.config.user_secrets_file}"
                )
            return

        if self.console:
            self.console.info(
                f"Loading user-supplied secrets from {self.config.user_secrets_file}"
            )

        with self.config.user_secrets_file.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    self.user_secrets[key.strip()] = value.strip()

        self.user_secrets_loaded = True
        if self.console:
            self.console.ok(f"Loaded {len(self.user_secrets)} secret(s) from file")

    def obtain_deterministic_secret(
        self,
        secret_label: str,
        cli_value: str | None,
        env_var_name: str,
        prompt_message: str,
    ) -> str:
        """Obtain a deterministic secret from CLI, env, file, or prompt.

        Args:
            secret_label: Human-readable label for error messages
            cli_value: Value provided via CLI argument
            env_var_name: Environment variable name to check
            prompt_message: Message to show when prompting user

        Returns:
            Secret value

        Raises:
            SystemExit: If secret cannot be obtained in non-interactive mode
        """
        # Priority: CLI > env var > user secrets file > prompt
        if cli_value:
            return cli_value

        env_value = os.environ.get(env_var_name)
        if env_value:
            return env_value

        # Load user secrets file if not already loaded
        if not self.user_secrets_loaded:
            self.load_user_supplied_secrets()

        if env_var_name in self.user_secrets:
            return self.user_secrets[env_var_name]

        if not self.config.non_interactive:
            if self.prompt_provider:
                return self.prompt_provider.prompt_for_secret(prompt_message)
            else:
                raise RuntimeError("No PromptProvider configured for interactive mode.")

        if self.console:
            self.console.error(
                f"{secret_label} not provided. "
                "Use CLI options or --user-secrets-file in non-interactive mode."
            )
        sys.exit(1)

    def write_secret(self, key: str, secret: str) -> bool:
        """Write secret using the SecretsManager.

        Args:
            key: Secret key name (e.g., "postgres_password")
            secret: Secret value to write

        Returns:
            True if written, False if kept existing
        """
        if self._secrets_manager.exists(key) and not self.config.overwrite_secrets:
            if self.console:
                self.console.info(f"Keeping existing {key} (use --force to rotate)")
            return False

        # Write using SecretsManager
        location = self._secrets_manager.write(key, secret)
        if self.console:
            self.console.ok(f"Generated {key} ({len(secret)} bytes) -> {location}")
        return True

    def generate_deterministic_secrets(self) -> None:
        """Generate deterministic secrets (OIDC client secrets, etc.)."""
        if self.console:
            self.console.info(
                "Handling deterministic secrets (OIDC client secrets, etc.)"
            )

        google_secret = self.obtain_deterministic_secret(
            secret_label="Google OIDC client secret",
            cli_value=self.config.oidc_google_secret,
            env_var_name="OIDC_GOOGLE_CLIENT_SECRET",
            prompt_message="Enter Google OIDC client secret",
        )

        microsoft_secret = self.obtain_deterministic_secret(
            secret_label="Microsoft OIDC client secret",
            cli_value=self.config.oidc_microsoft_secret,
            env_var_name="OIDC_MICROSOFT_CLIENT_SECRET",
            prompt_message="Enter Microsoft OIDC client secret",
        )

        keycloak_secret = self.obtain_deterministic_secret(
            secret_label="Keycloak OIDC client secret",
            cli_value=self.config.oidc_keycloak_secret,
            env_var_name="OIDC_KEYCLOAK_CLIENT_SECRET",
            prompt_message="Enter Keycloak OIDC client secret",
        )

        self.write_secret("oidc_google_client_secret", google_secret)
        self.write_secret("oidc_microsoft_client_secret", microsoft_secret)
        self.write_secret("oidc_keycloak_client_secret", keycloak_secret)

    def generate_all_secrets(self) -> None:
        """Generate all secrets."""
        if self.console:
            self.console.info("Generating cryptographically secure secrets...")
            self.console.print("")

        if not self.config.overwrite_secrets:
            if self.console:
                self.console.info(
                    "Existing secret files will be reused. Pass --force to regenerate."
                )

        # Generate all secret files
        generator = SecretGenerator()
        self.write_secret("postgres_password", generator.generate_db_password())
        self.write_secret("postgres_app_user_pw", generator.generate_db_password())
        self.write_secret("postgres_app_ro_pw", generator.generate_db_password())
        self.write_secret("postgres_app_owner_pw", generator.generate_db_password())
        self.write_secret("postgres_temporal_pw", generator.generate_db_password())
        self.write_secret("redis_password", generator.generate_db_password())
        self.write_secret("session_signing_secret", generator.generate_session_secret())
        self.write_secret("csrf_signing_secret", generator.generate_csrf_secret())

        self.generate_deterministic_secrets()

        if self.console:
            self.console.print("")
            self.console.ok("All secrets generated successfully!")
            self.console.info(
                "Files are created with 600 permissions (owner read/write only)"
            )
            self.console.warn(
                "Keep these files secure and never commit them to version control!"
            )

    def verify_secrets(self) -> None:
        """Verify existing secrets and certificates using SecretsManager."""
        if self.console:
            self.console.info("Verifying existing secrets and certificates...")
        all_good = True

        # Verify secrets using SecretsManager
        if self.console:
            self.console.info("Checking secret files...")
        for secret_type, min_length in SECRET_MIN_LENGTHS.items():
            key = secret_type.value
            result = self._secrets_manager.verify(key)

            if result.exists:
                size = result.size or 0
                perms = result.permissions or "???"

                if size >= min_length:
                    if result.valid:
                        if self.console:
                            self.console.ok(
                                f"{key}: OK ({size} bytes, permissions: {perms})"
                            )
                    else:
                        issues = ", ".join(result.issues)
                        if self.console:
                            self.console.warn(f"{key}: {issues}")
                else:
                    if self.console:
                        self.console.error(
                            f"{key}: Too short ({size} bytes, minimum: {min_length})"
                        )
                    all_good = False
            else:
                if self.console:
                    self.console.warn(f"{key}: Missing")
                all_good = False

        # Verify PKI certificates
        if self.console:
            self.console.info("Checking PKI certificates...")
        certs = self._secrets_manager.list_certs()

        if certs:
            for cert_key in certs:
                result = self._secrets_manager.verify(cert_key, SecretKind.CERT)
                if result.exists:
                    perms = result.permissions or "???"
                    if result.valid:
                        expiry_info = ""
                        if result.expires_at:
                            expiry_info = (
                                f", expires: {result.expires_at.strftime('%Y-%m-%d')}"
                            )
                        if self.console:
                            self.console.ok(
                                f"{cert_key}: OK (permissions: {perms}{expiry_info})"
                            )
                    else:
                        issues = ", ".join(result.issues)
                        if self.console:
                            self.console.warn(f"{cert_key}: {issues}")
                        all_good = False
                else:
                    if self.console:
                        self.console.warn(f"{cert_key}: Missing")
                    all_good = False
        else:
            if self.console:
                self.console.info(
                    "No PKI certificates found (use --pki to create them)"
                )

        if all_good:
            if self.console:
                self.console.ok("All secrets and certificates verified successfully!")
        else:
            if self.console:
                self.console.warn(
                    "Some secrets or certificates need attention. "
                    "Run without --verify to regenerate."
                )

    def list_secrets(self) -> None:
        """List all secrets and certificates using SecretsManager."""
        if not self.console:
            return

        self.console.info("Listing all secrets and certificates:")
        self.console.print("")
        self.console.print(f"{'Item':<45} {'Size':>10} {'Permissions':>10}")
        self.console.print(f"{'-' * 45} {'-' * 10} {'-' * 10}")

        files_found = False

        # List keys
        for key in self._secrets_manager.list_keys():
            result = self._secrets_manager.verify(key)
            if result.exists:
                size_str = f"{result.size} bytes" if result.size else "???"
                perms = result.permissions or "???"
                self.console.print(f"{key:<45} {size_str:>10} {perms:>10}")
                files_found = True

        # List certificates
        for cert in self._secrets_manager.list_certs():
            result = self._secrets_manager.verify(cert, SecretKind.CERT)
            if result.exists:
                size_str = f"{result.size} bytes" if result.size else "???"
                perms = result.permissions or "???"
                self.console.print(f"certs/{cert:<40} {size_str:>10} {perms:>10}")
                files_found = True

        if not files_found:
            self.console.warn("No secrets or certificates found")
