"""Secrets management abstraction layer.

Provides a pluggable interface for reading/writing secrets and certificates,
allowing different backends (files, Vault, K8s secrets, etc.).

Example:
    from src.infra.secrets import get_secrets_manager, SecretKind

    secrets = get_secrets_manager()

    # Keys (default)
    password = secrets.read("postgres_password")
    secrets.write("postgres_password", new_password)

    # Certificates
    cert = secrets.read("root-ca.crt", kind=SecretKind.CERT)
    secrets.write("postgres/server.crt", pem_content, kind=SecretKind.CERT)
"""

from .base import BackupInfo, SecretKind, SecretsManager, VerificationResult
from .crypto import CharSet, SecretGenerator
from .file_manager import FileSecretsManager
from .generator import (
    SECRET_MIN_LENGTHS,
    ConsoleProtocol,
    GeneratorConfig,
    PromptProvider,
    SecretGenerationOrchestrator,
    SecretType,
)
from .pki import SERVICE_SANS, PKICertificateGenerator, PKIGenerationResult, ServiceType

# Default factory - can be overridden for different environments
_manager_instance: SecretsManager | None = None


def get_secrets_manager() -> SecretsManager:
    """Get the configured secrets manager instance.

    Returns a singleton instance of the secrets manager.
    Default is FileSecretsManager using infra/secrets/keys/.

    Returns:
        Configured SecretsManager instance
    """
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = FileSecretsManager()
    return _manager_instance


def set_secrets_manager(manager: SecretsManager) -> None:
    """Set the secrets manager instance.

    Useful for testing or switching to different backends.

    Args:
        manager: SecretsManager implementation to use
    """
    global _manager_instance
    _manager_instance = manager


__all__ = [
    # Base abstractions
    "BackupInfo",
    "SecretKind",
    "SecretsManager",
    "VerificationResult",
    # Implementations
    "FileSecretsManager",
    # Crypto primitives
    "CharSet",
    "SecretGenerator",
    # PKI
    "PKICertificateGenerator",
    "PKIGenerationResult",
    "ServiceType",
    "SERVICE_SANS",
    # Orchestration
    "ConsoleProtocol",
    "GeneratorConfig",
    "PromptProvider",
    "SecretGenerationOrchestrator",
    "SecretType",
    "SECRET_MIN_LENGTHS",
    # Factory functions
    "get_secrets_manager",
    "set_secrets_manager",
]
