"""Abstract base class for secrets management.

Defines the interface that all secrets managers must implement.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class SecretKind(Enum):
    """Type of secret being stored/retrieved.

    KEY: Application secrets (passwords, API keys, signing secrets)
    CERT: Certificates and private keys (TLS certs, CA certs, key files)
    """

    KEY = "key"
    CERT = "cert"


@dataclass
class BackupInfo:
    """Information about a backup."""

    name: str
    """Backup identifier (e.g., 'backup_20260118_143022')"""

    timestamp: datetime
    """When the backup was created"""

    key_count: int = 0
    """Number of keys in this backup"""

    cert_count: int = 0
    """Number of certificates in this backup"""

    metadata: dict[str, str] = field(default_factory=dict)
    """Additional implementation-specific metadata"""


@dataclass
class VerificationResult:
    """Result of verifying a secret or certificate."""

    key: str
    """The key that was verified"""

    kind: SecretKind
    """Type of secret"""

    exists: bool
    """Whether the item exists"""

    valid: bool
    """Whether the item passes validation"""

    size: int | None = None
    """Size in bytes (if applicable)"""

    permissions: str | None = None
    """File permissions (if applicable, e.g., '600')"""

    expires_at: datetime | None = None
    """Expiration date for certificates"""

    issues: list[str] = field(default_factory=list)
    """List of validation issues found"""


class SecretsManager(ABC):
    """Abstract interface for secrets and certificate storage operations.

    Implementations handle the actual storage mechanism (files, Vault, K8s, etc.).
    Items are identified by a kind (KEY or CERT) and a logical identifier:
    - Keys: "postgres_password", "session_signing_secret"
    - Certs: "root-ca.crt", "postgres/server.key"

    Subclasses must implement:
        Core Operations:
        - read(key, kind) -> str | None
        - write(key, value, kind) -> Path | str
        - exists(key, kind) -> bool
        - delete(key, kind) -> bool
        - list_keys(prefix) -> list[str]
        - list_certs(prefix) -> list[str]
        - healthcheck() -> bool

        Certificate Operations:
        - append_to_ca_bundle(cert_content, comment) -> str

        Backup Operations:
        - backup_all(name) -> BackupInfo
        - list_backups() -> list[BackupInfo]
        - restore_backup(name) -> bool
        - delete_backup(name) -> bool

        Verification:
        - verify(key, kind) -> VerificationResult
        - verify_all() -> list[VerificationResult]
    """

    @abstractmethod
    def read(self, key: str, kind: SecretKind = SecretKind.KEY) -> str | None:
        """Read a secret or certificate by key.

        Args:
            key: Logical identifier
                 - For KEY: "postgres_password", "session_signing_secret"
                 - For CERT: "root-ca.crt", "postgres/server.key"
            kind: Type of secret (KEY or CERT). Defaults to KEY.

        Returns:
            Content as string, or None if not found
        """
        ...

    @abstractmethod
    def write(
        self,
        key: str,
        value: str,
        kind: SecretKind = SecretKind.KEY,
        *,
        backup: bool = False,
    ) -> Path | str:
        """Write a secret or certificate.

        Args:
            key: Logical identifier
                 - For KEY: "postgres_password", "session_signing_secret"
                 - For CERT: "root-ca.crt", "postgres/server.key"
            value: Content to store (secret value or PEM-encoded certificate/key)
            kind: Type of secret (KEY or CERT). Defaults to KEY.
            backup: If True and item exists, create a backup first

        Returns:
            Location identifier (file path, URI, etc.)
        """
        ...

    @abstractmethod
    def exists(self, key: str, kind: SecretKind = SecretKind.KEY) -> bool:
        """Check if a secret or certificate exists.

        Args:
            key: Logical identifier
            kind: Type of secret (KEY or CERT). Defaults to KEY.

        Returns:
            True if item exists
        """
        ...

    @abstractmethod
    def delete(self, key: str, kind: SecretKind = SecretKind.KEY) -> bool:
        """Delete a secret or certificate.

        Args:
            key: Logical identifier
            kind: Type of secret (KEY or CERT). Defaults to KEY.

        Returns:
            True if deleted, False if didn't exist
        """
        ...

    @abstractmethod
    def list_keys(self, prefix: str | None = None) -> list[str]:
        """List all secret keys (kind=KEY).

        Args:
            prefix: Optional prefix to filter results

        Returns:
            List of secret key identifiers
            Example: ["postgres_password", "session_signing_secret", ...]
        """
        ...

    @abstractmethod
    def list_certs(self, prefix: str | None = None) -> list[str]:
        """List all certificate identifiers (kind=CERT).

        Args:
            prefix: Optional prefix to filter results
                    Example: "postgres/" for postgres certs only

        Returns:
            List of certificate identifiers
            Example: ["root-ca.crt", "postgres/server.key", ...]
        """
        ...

    @abstractmethod
    def healthcheck(self) -> bool:
        """Check if the secrets backend is accessible and healthy.

        Returns:
            True if backend is reachable and operational, False otherwise
        """
        ...

    # -------------------------------------------------------------------------
    # Convenience Methods (non-abstract)
    # -------------------------------------------------------------------------

    def read_or_raise(self, key: str, kind: SecretKind = SecretKind.KEY) -> str:
        """Read a secret or certificate, raising if not found.

        Args:
            key: Logical identifier
            kind: Type of secret (KEY or CERT). Defaults to KEY.

        Returns:
            Content as string

        Raises:
            KeyError: If item doesn't exist
        """
        value = self.read(key, kind)
        if value is None:
            raise KeyError(f"{kind.value.title()} not found: {key}")
        return value

    def ensure(
        self,
        key: str,
        kind: SecretKind = SecretKind.KEY,
        default_factory: Callable[[], str] | None = None,
    ) -> str:
        """Get a secret or certificate, optionally creating it if missing.

        Args:
            key: Logical identifier
            kind: Type of secret (KEY or CERT). Defaults to KEY.
            default_factory: Optional callable that returns default value

        Returns:
            Content as string

        Raises:
            KeyError: If item doesn't exist and no default_factory provided
        """
        value = self.read(key, kind)
        if value is not None:
            return value

        if default_factory is None:
            raise KeyError(f"{kind.value.title()} not found: {key}")

        new_value = default_factory()
        self.write(key, new_value, kind)
        return new_value

    # -------------------------------------------------------------------------
    # Certificate-Specific Helper Methods
    # -------------------------------------------------------------------------

    @abstractmethod
    def append_to_ca_bundle(self, cert_content: str, comment: str | None = None) -> str:
        """Append a certificate to the CA bundle.

        Creates the bundle if it doesn't exist. Skips if content already present.

        Args:
            cert_content: Certificate content to append (PEM format)
            comment: Optional comment to add before the certificate

        Returns:
            The full CA bundle content after the operation
        """
        ...

    # -------------------------------------------------------------------------
    # Backup Operations (abstract)
    # -------------------------------------------------------------------------

    @abstractmethod
    def backup_all(self, name: str | None = None) -> BackupInfo:
        """Create a backup of all secrets and certificates.

        Args:
            name: Optional backup name. If not provided, a timestamped name is used.

        Returns:
            BackupInfo describing the created backup

        Raises:
            RuntimeError: If backup creation fails
        """
        ...

    @abstractmethod
    def list_backups(self) -> list[BackupInfo]:
        """List all available backups.

        Returns:
            List of BackupInfo, sorted by timestamp (newest first)
        """
        ...

    @abstractmethod
    def restore_backup(self, name: str) -> bool:
        """Restore secrets and certificates from a backup.

        Args:
            name: Backup identifier to restore from

        Returns:
            True if restored successfully

        Raises:
            KeyError: If backup doesn't exist
            RuntimeError: If restoration fails
        """
        ...

    @abstractmethod
    def delete_backup(self, name: str) -> bool:
        """Delete a backup.

        Args:
            name: Backup identifier to delete

        Returns:
            True if deleted, False if backup didn't exist
        """
        ...

    # -------------------------------------------------------------------------
    # Verification Operations (abstract)
    # -------------------------------------------------------------------------

    @abstractmethod
    def verify(self, key: str, kind: SecretKind = SecretKind.KEY) -> VerificationResult:
        """Verify a single secret or certificate.

        Checks:
        - Existence
        - Non-empty content
        - For certs: PEM format validity, expiration
        - Permissions (implementation-specific)

        Args:
            key: Logical identifier
            kind: Type of secret (KEY or CERT). Defaults to KEY.

        Returns:
            VerificationResult with validation details
        """
        ...

    @abstractmethod
    def verify_all(self) -> list[VerificationResult]:
        """Verify all secrets and certificates.

        Returns:
            List of VerificationResult for all items
        """
        ...

    # -------------------------------------------------------------------------
    # Convenience Methods (non-abstract)
    # -------------------------------------------------------------------------

    def get_latest_backup(self) -> BackupInfo | None:
        """Get the most recent backup.

        Returns:
            BackupInfo for latest backup, or None if no backups exist
        """
        backups = self.list_backups()
        return backups[0] if backups else None

    def pop_backup(self) -> BackupInfo | None:
        """Restore from the latest backup and delete it.

        Convenience method that combines restore_backup() and delete_backup().

        Returns:
            BackupInfo of the restored backup, or None if no backups exist

        Raises:
            RuntimeError: If restoration fails
        """
        latest = self.get_latest_backup()
        if latest is None:
            return None

        self.restore_backup(latest.name)
        self.delete_backup(latest.name)
        return latest
