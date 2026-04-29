"""Fly.io-specific database settings.

Extends DbSettings with Fly-specific behavior for password retrieval.
"""

from pathlib import Path
from typing import Self

from src.infra.postgres.connection import DbSettings
from src.infra.secrets import SecretsManager, get_secrets_manager

# Secret key for postgres superuser password
SUPERUSER_PASSWORD_KEY = "postgres_password"


class FlyDbSettings(DbSettings):
    """Database settings for Fly.io deployments.

    Extends DbSettings with Fly-specific behavior:
    - For managed postgres: retrieves superuser password from Fly MPG connection string
    - For unmanaged postgres: retrieves from OPERATOR_PASSWORD via SSH

    The superuser password is cached after first retrieval.
    """

    # Fly-specific fields
    is_managed: bool = False
    cluster_id: str | None = None

    def ensure_superuser_password(self) -> Self:
        """Ensure superuser password is set.

        For Fly deployments:
        - Managed (MPG): retrieves from `fly mpg connection-string`
        - Unmanaged (legacy): retrieves from OPERATOR_PASSWORD via SSH

        The password is cached after first retrieval.

        Returns:
            Self with superuser_password populated

        Raises:
            RuntimeError: If password cannot be retrieved from Fly
        """
        if self.superuser_password:
            return self  # Already set, use cached value

        if not self.cluster_id:
            # No cluster ID - fall back to parent behavior (secrets file)
            return super().ensure_superuser_password()

        # Import here to avoid circular imports
        from src.infra.flyio.controller import FlyCtlControllerSync

        controller = FlyCtlControllerSync()

        if self.is_managed:
            # Managed postgres - get password from connection string
            success, conn_str = controller.mpg_connection_string(self.cluster_id)
            if not success:
                raise RuntimeError(
                    f"Failed to retrieve connection string from Fly MPG: {conn_str}"
                )

            # Re-parse only to extract the password; urlparse handles credentials
            from urllib.parse import urlparse

            parsed = urlparse(conn_str)
            if not parsed.password:
                raise RuntimeError(
                    "Fly MPG connection string does not contain password"
                )

            self.superuser_password = parsed.password
        else:
            # Unmanaged postgres - get OPERATOR_PASSWORD via SSH
            success, result = controller.postgres_get_superuser_password(
                self.cluster_id
            )
            if not success:
                raise RuntimeError(
                    f"Failed to retrieve superuser password from Fly: {result}"
                )

            self.superuser_password = result

        return self

    def get_local_superuser_password(
        self, secrets_manager: SecretsManager | None = None
    ) -> str:
        """Get the local superuser password from secrets storage.

        This retrieves the password from local secrets, not from Fly.
        Useful when you need to know the target password for syncing.

        Args:
            secrets_manager: Optional SecretsManager instance. If not provided,
                           uses the default manager from get_secrets_manager().

        Returns:
            The local superuser password from secrets storage

        Raises:
            KeyError: If password not found in secrets
        """
        manager = secrets_manager or get_secrets_manager()
        return manager.read_or_raise(SUPERUSER_PASSWORD_KEY)

    @property
    def is_superuser_password_managed_by_fly(self) -> bool:
        """Check if the superuser password is managed by Fly.

        For managed postgres, Fly owns the superuser credentials and we should
        not attempt to change them.

        Returns:
            True if superuser password should not be modified
        """
        return self.is_managed

    def sync_superuser_password_to_local(
        self, secrets_manager: SecretsManager | None = None
    ) -> Path | str:
        """Sync the superuser password from Fly to local secrets storage.

        For managed postgres, we can't change the password - Fly owns it.
        Instead, we fetch the current password from Fly and write it to our
        local secrets so that verify and other tools can use it.

        Args:
            secrets_manager: Optional SecretsManager instance. If not provided,
                           uses the default manager from get_secrets_manager().

        Returns:
            Location where secret was written (path or URI)

        Raises:
            RuntimeError: If password cannot be retrieved from Fly
            ValueError: If called on unmanaged postgres (wrong direction)
        """
        if not self.is_managed:
            raise ValueError(
                "sync_superuser_password_to_local is only for managed postgres. "
                "For unmanaged postgres, sync goes local → Fly, not Fly → local."
            )

        # Ensure we have the password from Fly
        self.ensure_superuser_password()

        if not self.superuser_password:
            raise RuntimeError("Failed to retrieve superuser password from Fly")

        # Write to secrets storage
        manager = secrets_manager or get_secrets_manager()
        return manager.write(SUPERUSER_PASSWORD_KEY, self.superuser_password)
