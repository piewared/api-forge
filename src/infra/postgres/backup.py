"""PostgreSQL backup functionality.

Provides database backup using pg_dump with compression and checksums.
"""

import gzip
import hashlib
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from src.cli.shared.console import console
from src.infra.postgres.connection import PostgresConnection


class PostgresBackup:
    """Creates PostgreSQL database backups.

    Supports both custom format (for pg_restore) and SQL format.
    Includes compression and SHA256 checksums.
    """

    def __init__(
        self, connection: PostgresConnection, backup_dir: Path, retention_days: int = 7
    ) -> None:
        self._settings = connection.settings
        self._connection = connection
        self._console = console
        self.backup_dir = backup_dir
        self.retention_days = retention_days

    def create_backup(
        self,
        *,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> tuple[bool, str]:
        """Create a database backup.

        Args:
            password: Password for database user (defaults to ro_user password)
            database: Database to backup (defaults to app_db)
            user: User for backup (defaults to ro_user for read-only access)

        Returns:
            Tuple of (success, backup_path or error message)
        """
        s = self._settings

        database = database or s.app_db
        user = user or s.ro_user

        if not password:
            s.ensure_ro_user_password()

        password = password or s.ro_user_password

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_{database}_{timestamp}"

        self._console.print("\n[bold]== Creating PostgreSQL Backup ==[/bold]")
        self._console.info(f"Database: {database}")
        self._console.info(f"User: {user}")
        self._console.info(f"Host: {s.host}:{s.port}")
        self._console.info(f"Backup dir: {self.backup_dir}")

        # Ensure backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        custom_path = self.backup_dir / f"{backup_name}.dump"
        sql_path = self.backup_dir / f"{backup_name}.sql"
        sql_gz_path = self.backup_dir / f"{backup_name}.sql.gz"

        try:
            # Create custom format backup
            self._console.info("Creating custom format backup...")
            env = {"PGPASSWORD": password}
            # Remove any None values from env
            env_clean = {
                k: v for k, v in {**os.environ, **env}.items() if v is not None
            }
            result = subprocess.run(
                [
                    "pg_dump",
                    "-h",
                    s.host,
                    "-p",
                    str(s.port),
                    "-U",
                    user,
                    "-Fc",
                    "-f",
                    str(custom_path),
                    database,
                ],
                env=env_clean,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return False, f"pg_dump failed: {result.stderr}"
            self._console.ok(f"Custom format: {custom_path.name}")

            env_clean = {
                k: v for k, v in {**os.environ, **env}.items() if v is not None
            }
            result = subprocess.run(
                [
                    "pg_dump",
                    "-h",
                    s.host,
                    "-p",
                    str(s.port),
                    "-U",
                    user,
                    "-f",
                    str(sql_path),
                    database,
                ],
                env=env_clean,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return False, f"pg_dump SQL failed: {result.stderr}"

            # Compress SQL backup
            self._console.info("Compressing SQL backup...")
            with open(sql_path, "rb") as f_in:
                with gzip.open(sql_gz_path, "wb") as f_out:
                    f_out.writelines(f_in)
            sql_path.unlink()  # Remove uncompressed
            self._console.ok(f"Compressed SQL: {sql_gz_path.name}")

            # Create checksums
            self._console.info("Creating checksums...")
            for path in [custom_path, sql_gz_path]:
                checksum = self._sha256(path)
                checksum_path = path.with_suffix(path.suffix + ".sha256")
                checksum_path.write_text(f"{checksum}  {path.name}\n")
            self._console.ok("Checksums created")

            # Clean old backups
            self._cleanup_old_backups()

            return True, str(custom_path)

        except Exception as e:
            return False, str(e)

    def _sha256(self, path: Path) -> str:
        """Calculate SHA256 checksum of file."""
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _cleanup_old_backups(self) -> None:
        """Remove backups older than retention_days."""
        cutoff = time.time() - (self.retention_days * 86400)
        removed = 0

        for path in self.backup_dir.glob("backup_*"):
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1

        if removed:
            self._console.info(f"Cleaned up {removed} old backup file(s)")


def create_backup(
    connection: PostgresConnection,
    backup_dir: Path,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> tuple[bool, str | None]:
    """Create a database backup.

    Args:
        password: Password for database user
        database: Database to backup
        user: User to connect as
        settings: Optional DbSettings (loaded if not provided)
        backup_dir: Optional backup directory

    Returns:
        Tuple of (success, backup_path or error message)
    """

    backup = PostgresBackup(connection, backup_dir=backup_dir)
    return backup.create_backup(user=user, password=password, database=database)
