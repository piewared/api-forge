"""File-based secrets manager implementation.

Stores secrets and certificates as individual files in a directory structure.

Default locations:
    - Secrets (KEY): infra/secrets/keys/<key>.txt
    - Certificates (CERT): infra/secrets/certs/<path>
    - CA Bundle: infra/secrets/certs/ca-bundle.crt
    - Backups: infra/secrets/backups/backup_<timestamp>/

Examples:
    manager = FileSecretsManager()

    # Keys (secrets)
    manager.write("postgres_password", "secret123")
    manager.read("postgres_password")
    manager.list_keys()

    # Certs
    manager.write("root-ca.crt", pem_content, kind=SecretKind.CERT)
    manager.read("postgres/server.key", kind=SecretKind.CERT)
    manager.list_certs()

    # Backups
    backup = manager.backup_all()
    manager.list_backups()
    manager.restore_backup(backup.name)
"""

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from src.utils.paths import get_project_root

from .base import BackupInfo, SecretKind, SecretsManager, VerificationResult

# Default base directory for all secrets/certs
DEFAULT_SECRETS_BASE = get_project_root() / "infra" / "secrets"
# Default secrets (keys) directory
DEFAULT_SECRETS_DIR = DEFAULT_SECRETS_BASE / "keys"
# Default certificates directory
DEFAULT_CERTS_DIR = DEFAULT_SECRETS_BASE / "certs"
# Default backups directory
DEFAULT_BACKUPS_DIR = DEFAULT_SECRETS_BASE / "backups"
# CA bundle filename
CA_BUNDLE_FILENAME = "ca-bundle.crt"


class FileSecretsManager(SecretsManager):
    """Secrets manager that stores secrets and certificates as files.

    Secrets (KEY) are stored in a keys/ directory:
        infra/secrets/keys/postgres_password.txt
        infra/secrets/keys/redis_password.txt

    Certificates (CERT) are stored in a certs/ directory:
        infra/secrets/certs/root-ca.crt
        infra/secrets/certs/postgres/server.key

    Backups are stored in a backups/ directory:
        infra/secrets/backups/backup_20260118_143022/

    File format is plain text with optional trailing whitespace stripped on read.
    """

    def __init__(
        self,
        secrets_dir: Path | None = None,
        certs_dir: Path | None = None,
        backups_dir: Path | None = None,
    ) -> None:
        """Initialize the file secrets manager.

        Args:
            secrets_dir: Directory to store secrets (keys).
                        Defaults to infra/secrets/keys/
            certs_dir: Directory to store certificates.
                       Defaults to infra/secrets/certs/
            backups_dir: Directory to store backups.
                         Defaults to infra/secrets/backups/
        """
        self._secrets_dir = secrets_dir or DEFAULT_SECRETS_DIR
        self._certs_dir = certs_dir or DEFAULT_CERTS_DIR
        self._backups_dir = backups_dir or DEFAULT_BACKUPS_DIR

    @property
    def secrets_dir(self) -> Path:
        """Get the secrets (keys) directory path."""
        return self._secrets_dir

    @property
    def certs_dir(self) -> Path:
        """Get the certificates directory path."""
        return self._certs_dir

    @property
    def backups_dir(self) -> Path:
        """Get the backups directory path."""
        return self._backups_dir

    def _key_to_path(self, key: str, kind: SecretKind) -> Path:
        """Convert a logical key to its file path.

        Args:
            key: Logical identifier (e.g., "postgres_password" or "root-ca.crt")
            kind: Type of secret (KEY or CERT)

        Returns:
            Absolute path to the file
        """
        if kind == SecretKind.CERT:
            return self._certs_dir / key
        else:
            # Secret key - add .txt extension if not present
            filename = key if key.endswith(".txt") else f"{key}.txt"
            return self._secrets_dir / filename

    def _path_to_key(self, path: Path, kind: SecretKind) -> str:
        """Convert a file path to its logical key.

        Args:
            path: Absolute path to file
            kind: Type of secret (KEY or CERT)

        Returns:
            Logical key (e.g., "postgres_password" or "postgres/server.key")
        """
        if kind == SecretKind.CERT:
            return str(path.relative_to(self._certs_dir))
        else:
            return path.stem  # Remove .txt extension

    def read(self, key: str, kind: SecretKind = SecretKind.KEY) -> str | None:
        """Read a secret or certificate from file.

        Args:
            key: Logical identifier (e.g., "postgres_password" or "root-ca.crt")
            kind: Type of secret (KEY or CERT). Defaults to KEY.

        Returns:
            Content with trailing whitespace stripped, or None if file doesn't exist
        """
        path = self._key_to_path(key, kind)
        if not path.exists():
            return None

        return path.read_text().strip()

    def write(
        self,
        key: str,
        value: str,
        kind: SecretKind = SecretKind.KEY,
        *,
        backup: bool = False,
    ) -> Path:
        """Write a secret or certificate to file.

        Creates parent directories if needed.
        Does NOT add trailing newline - stores exact value.

        Args:
            key: Logical identifier (e.g., "postgres_password" or "root-ca.crt")
            value: Content to store
            kind: Type of secret (KEY or CERT). Defaults to KEY.
            backup: If True and file exists, create a .bak backup first

        Returns:
            Path to the written file
        """
        path = self._key_to_path(key, kind)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Backup existing file if requested
        if backup and path.exists():
            backup_path = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup_path)

        path.write_text(value)
        return path

    def exists(self, key: str, kind: SecretKind = SecretKind.KEY) -> bool:
        """Check if a secret or certificate file exists.

        Args:
            key: Logical identifier (e.g., "postgres_password" or "root-ca.crt")
            kind: Type of secret (KEY or CERT). Defaults to KEY.

        Returns:
            True if the file exists
        """
        return self._key_to_path(key, kind).exists()

    def delete(self, key: str, kind: SecretKind = SecretKind.KEY) -> bool:
        """Delete a secret or certificate file.

        Args:
            key: Logical identifier (e.g., "postgres_password" or "root-ca.crt")
            kind: Type of secret (KEY or CERT). Defaults to KEY.

        Returns:
            True if deleted, False if file didn't exist
        """
        path = self._key_to_path(key, kind)
        if not path.exists():
            return False

        path.unlink()
        return True

    def list_keys(self, prefix: str | None = None) -> list[str]:
        """List all secret keys (kind=KEY).

        Args:
            prefix: Optional prefix to filter results

        Returns:
            List of secret key identifiers (without .txt extension)
            Example: ["postgres_password", "redis_password", ...]
        """
        keys: list[str] = []

        if self._secrets_dir.exists():
            for p in self._secrets_dir.glob("*.txt"):
                if p.is_file():
                    key = self._path_to_key(p, SecretKind.KEY)
                    if prefix is None or key.startswith(prefix):
                        keys.append(key)

        return sorted(keys)

    def list_certs(self, prefix: str | None = None) -> list[str]:
        """List all certificate identifiers (kind=CERT).

        Args:
            prefix: Optional prefix to filter results
                    Example: "postgres/" for postgres certs only

        Returns:
            List of certificate identifiers
            Example: ["root-ca.crt", "postgres/server.key", ...]
        """
        certs: list[str] = []

        if self._certs_dir.exists():
            for p in self._certs_dir.rglob("*"):
                if p.is_file():
                    cert_key = self._path_to_key(p, SecretKind.CERT)
                    if prefix is None or cert_key.startswith(prefix):
                        certs.append(cert_key)

        return sorted(certs)

    def healthcheck(self) -> bool:
        """Check if the secrets backend is accessible and healthy.

        Verifies that the secrets and certs directories exist and are accessible.

        Returns:
            True if directories are accessible, False otherwise
        """
        try:
            # Check secrets directory
            if not self._secrets_dir.exists():
                # Try to create it - if we can, it's accessible
                self._secrets_dir.mkdir(parents=True, exist_ok=True)

            # Verify we can read the directory
            list(self._secrets_dir.iterdir())

            # Check certs directory (optional - may not exist yet)
            if self._certs_dir.exists():
                list(self._certs_dir.iterdir())

            return True
        except (OSError, PermissionError):
            return False

    def append_to_ca_bundle(self, cert_content: str, comment: str | None = None) -> str:
        """Append a certificate to the CA bundle.

        Creates the bundle if it doesn't exist. Skips if content already present.

        Args:
            cert_content: Certificate content to append (PEM format)
            comment: Optional comment to add before the certificate

        Returns:
            The full CA bundle content after the operation
        """
        bundle_path = self._certs_dir / CA_BUNDLE_FILENAME
        bundle_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing content (if any)
        existing_content = ""
        if bundle_path.exists():
            existing_content = bundle_path.read_text()

        # Check if cert already present
        if cert_content.strip() in existing_content:
            return existing_content

        # Build new content to append
        new_content = ""
        if comment:
            new_content += f"# {comment}\n"
        new_content += cert_content.strip() + "\n"

        # Append to bundle
        with bundle_path.open("a") as f:
            if existing_content and not existing_content.endswith("\n"):
                f.write("\n")
            f.write(new_content)

        return bundle_path.read_text()

    # -------------------------------------------------------------------------
    # Backup Operations
    # -------------------------------------------------------------------------

    def backup_all(self, name: str | None = None) -> BackupInfo:
        """Create a backup of all secrets and certificates.

        Creates a timestamped backup directory containing copies of:
        - All files from keys/ directory
        - All files from certs/ directory (preserving subdirectory structure)

        Args:
            name: Optional backup name. If not provided, uses 'backup_YYYYMMDD_HHMMSS'.

        Returns:
            BackupInfo describing the created backup

        Raises:
            RuntimeError: If backup creation fails
        """
        timestamp = datetime.now()
        backup_name = name or f"backup_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        backup_dir = self._backups_dir / backup_name

        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            key_count = 0
            cert_count = 0

            # Backup keys directory
            if self._secrets_dir.exists() and any(self._secrets_dir.iterdir()):
                backup_keys_dir = backup_dir / "keys"
                backup_keys_dir.mkdir(parents=True, exist_ok=True)
                for file_path in self._secrets_dir.glob("*.txt"):
                    if file_path.is_file():
                        shutil.copy2(file_path, backup_keys_dir / file_path.name)
                        key_count += 1

            # Backup certs directory (preserving structure)
            if self._certs_dir.exists() and any(self._certs_dir.rglob("*")):
                backup_certs_dir = backup_dir / "certs"
                shutil.copytree(
                    self._certs_dir,
                    backup_certs_dir,
                    dirs_exist_ok=True,
                )
                cert_count = sum(1 for _ in backup_certs_dir.rglob("*") if _.is_file())

            return BackupInfo(
                name=backup_name,
                timestamp=timestamp,
                key_count=key_count,
                cert_count=cert_count,
                metadata={"path": str(backup_dir)},
            )
        except (OSError, PermissionError) as e:
            raise RuntimeError(f"Failed to create backup: {e}") from e

    def list_backups(self) -> list[BackupInfo]:
        """List all available backups.

        Returns:
            List of BackupInfo, sorted by timestamp (newest first)
        """
        backups: list[BackupInfo] = []

        if not self._backups_dir.exists():
            return backups

        for backup_dir in sorted(
            self._backups_dir.glob("backup_*"),
            key=lambda p: p.name,
            reverse=True,
        ):
            if not backup_dir.is_dir():
                continue

            # Parse timestamp from directory name
            backup_name = backup_dir.name
            try:
                timestamp_str = backup_name.replace("backup_", "")
                timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            except ValueError:
                # Non-standard backup name, use directory mtime
                timestamp = datetime.fromtimestamp(backup_dir.stat().st_mtime)

            # Count files
            key_count = 0
            cert_count = 0
            if (backup_dir / "keys").is_dir():
                key_count = sum(
                    1 for _ in (backup_dir / "keys").glob("*.txt") if _.is_file()
                )
            if (backup_dir / "certs").is_dir():
                cert_count = sum(
                    1 for _ in (backup_dir / "certs").rglob("*") if _.is_file()
                )

            backups.append(
                BackupInfo(
                    name=backup_name,
                    timestamp=timestamp,
                    key_count=key_count,
                    cert_count=cert_count,
                    metadata={"path": str(backup_dir)},
                )
            )

        return backups

    def restore_backup(self, name: str) -> bool:
        """Restore secrets and certificates from a backup.

        Restores all files from the backup, overwriting current files.
        Sets appropriate permissions (600 for keys, 600/644 for certs).

        Args:
            name: Backup identifier to restore from

        Returns:
            True if restored successfully

        Raises:
            KeyError: If backup doesn't exist
            RuntimeError: If restoration fails
        """
        backup_dir = self._backups_dir / name

        if not backup_dir.exists():
            raise KeyError(f"Backup not found: {name}")

        try:
            # Restore keys
            backup_keys = backup_dir / "keys"
            if backup_keys.is_dir():
                self._secrets_dir.mkdir(parents=True, exist_ok=True)
                for file_path in backup_keys.glob("*"):
                    if file_path.is_file():
                        target = self._secrets_dir / file_path.name
                        shutil.copy2(file_path, target)
                        target.chmod(0o600)

            # Restore certs (preserving structure)
            backup_certs = backup_dir / "certs"
            if backup_certs.is_dir():
                self._certs_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(
                    backup_certs,
                    self._certs_dir,
                    dirs_exist_ok=True,
                )
                # Fix permissions
                for key_file in self._certs_dir.rglob("*.key"):
                    key_file.chmod(0o600)
                for crt_file in self._certs_dir.rglob("*.crt"):
                    crt_file.chmod(0o644)
                for pem_file in self._certs_dir.rglob("*.pem"):
                    pem_file.chmod(0o644)

            return True
        except (OSError, PermissionError) as e:
            raise RuntimeError(f"Failed to restore backup: {e}") from e

    def delete_backup(self, name: str) -> bool:
        """Delete a backup.

        Args:
            name: Backup identifier to delete

        Returns:
            True if deleted, False if backup didn't exist
        """
        backup_dir = self._backups_dir / name

        if not backup_dir.exists():
            return False

        shutil.rmtree(backup_dir)
        return True

    # -------------------------------------------------------------------------
    # Verification Operations
    # -------------------------------------------------------------------------

    def verify(self, key: str, kind: SecretKind = SecretKind.KEY) -> VerificationResult:
        """Verify a single secret or certificate.

        Checks:
        - Existence
        - Non-empty content
        - File permissions
        - For certs: PEM format validity, expiration (via openssl)

        Args:
            key: Logical identifier
            kind: Type of secret (KEY or CERT). Defaults to KEY.

        Returns:
            VerificationResult with validation details
        """
        path = self._key_to_path(key, kind)
        issues: list[str] = []

        # Check existence
        if not path.exists():
            return VerificationResult(
                key=key,
                kind=kind,
                exists=False,
                valid=False,
                issues=["File does not exist"],
            )

        # Get file stats
        stat = path.stat()
        size = stat.st_size
        perms = oct(stat.st_mode)[-3:]

        # Check non-empty
        if size == 0:
            issues.append("File is empty")

        # Check permissions
        if kind == SecretKind.KEY:
            if perms != "600":
                issues.append(f"Permissions should be 600, got {perms}")
        else:
            # Certs: .key files should be 600, others can be 644
            if key.endswith(".key"):
                if perms != "600":
                    issues.append(f"Private key permissions should be 600, got {perms}")
            elif perms not in ("600", "644"):
                issues.append(
                    f"Certificate permissions should be 600 or 644, got {perms}"
                )

        # For certificates, check validity with openssl
        expires_at: datetime | None = None
        if kind == SecretKind.CERT and key.endswith(".crt"):
            try:
                # Check if certificate is valid (not expired within 24 hours)
                check_result = subprocess.run(
                    [
                        "openssl",
                        "x509",
                        "-in",
                        str(path),
                        "-noout",
                        "-checkend",
                        "86400",
                    ],
                    capture_output=True,
                )
                if check_result.returncode != 0:
                    issues.append("Certificate is expired or expiring within 24 hours")

                # Get expiration date
                enddate_result = subprocess.run(
                    ["openssl", "x509", "-in", str(path), "-noout", "-enddate"],
                    capture_output=True,
                    text=True,
                )
                if enddate_result.returncode == 0:
                    # Parse "notAfter=Mon Jan 18 14:30:22 2027 GMT"
                    enddate_str = enddate_result.stdout.strip().replace("notAfter=", "")
                    try:
                        expires_at = datetime.strptime(
                            enddate_str, "%b %d %H:%M:%S %Y %Z"
                        )
                    except ValueError:
                        pass  # Couldn't parse date
            except FileNotFoundError:
                # openssl not available
                pass

        return VerificationResult(
            key=key,
            kind=kind,
            exists=True,
            valid=len(issues) == 0,
            size=size,
            permissions=perms,
            expires_at=expires_at,
            issues=issues,
        )

    def verify_all(self) -> list[VerificationResult]:
        """Verify all secrets and certificates.

        Returns:
            List of VerificationResult for all items
        """
        results: list[VerificationResult] = []

        # Verify all keys
        for key in self.list_keys():
            results.append(self.verify(key, SecretKind.KEY))

        # Verify all certs
        for cert in self.list_certs():
            results.append(self.verify(cert, SecretKind.CERT))

        return results
