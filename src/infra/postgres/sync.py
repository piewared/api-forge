"""PostgreSQL password synchronization.

Syncs database user role names and passwords from secret files to PostgreSQL.
"""

from pathlib import Path

import psycopg2

from src.cli.deployment.base import BaseDeployer
from src.cli.deployment.status_display import is_temporal_enabled
from src.cli.shared.console import console
from src.infra.constants import DEFAULT_CONSTANTS
from src.infra.utils.service_config import is_bundled_postgres_enabled

from .connection import PostgresConnection


class PostgresPasswordSync:
    """Synchronizes PostgreSQL user passwords from secret files.

    For both Docker Compose and Kubernetes deployments.
    """

    def __init__(
        self,
        connection: PostgresConnection,
        deployer: BaseDeployer,
        secrets_dirs: list[Path],
    ) -> None:
        self._deployer = deployer
        self._settings = connection.settings
        self._connection = connection
        self._console = console
        self._secrets_dirs = secrets_dirs

    def _read_secret(self, filename: str) -> str | None:
        """Read a secret from file.

        Tries secrets_dir first, then keys_dir.
        """
        for base in self._secrets_dirs:
            path = base / filename
            if path.exists():
                return path.read_text().strip()
        return None

    def sync_bundled_superuser_password(self) -> bool:
        """Sync the bundled PostgreSQL superuser password by deploying secrets and restarting the bundled postgres pod/container.

        The container/pod will pick up the new password on restart.

        Returns:
            True if sync succeeded
        """
        if not is_bundled_postgres_enabled():
            self._console.info(
                "Bundled PostgreSQL is not enabled; skipping superuser password sync"
            )
            return True

        # Step 1: Deploy secrets to K8s so the pod can pick them up on restart
        if not self._deployer.deploy_secrets():
            return False

        # Step 2: Restart PostgreSQL to pick up new secrets
        # This is done BEFORE port-forwarding since it kills the pod
        if not self._deployer.restart_resource(
            label=DEFAULT_CONSTANTS.POSTGRES_RESOURCE_NAME,
            resource_type="statefulset",
            timeout=120,
        ):
            return False

        return True

    def sync_user_roles_and_passwords(self) -> bool:
        """Run initialization after PostgreSQL restart with fresh port-forward."""
        from src.infra.postgres import PostgresInitializer

        self._console.info(
            "Re-running idempotent initialization to sync roles and passwords"
        )
        # Step 1: Re-run initialization
        initializer = PostgresInitializer(connection=self._connection)
        success = initializer.initialize()

        if success:
            self._console.info("Fixing database and schema ownership if needed")
            if not self._fix_ownership():
                success = False

        return success

    def _fix_ownership(self) -> bool:
        """Fix ownership of databases and schemas to use correct owner roles.

        Returns:
            True if ownership was fixed successfully
        """
        s = self._settings
        conn = self._connection
        success = True

        try:
            # Fix app database ownership
            self._console.info(f"Ensuring {s.app_db} is owned by {s.owner_user}")
            conn.execute_script(
                f"ALTER DATABASE {s.app_db} OWNER TO {s.owner_user}",
                database=self._settings.postgres_db,
            )

            # Fix app schema ownership
            self._console.info(f"Ensuring schema app is owned by {s.owner_user}")
            conn.execute_script(
                f"ALTER SCHEMA app OWNER TO {s.owner_user}",
                database=s.app_db,
            )

            if is_temporal_enabled():
                # Fix Temporal database ownership
                self._console.info(
                    f"Ensuring {s.temporal_db} is owned by {s.temporal_owner}"
                )
                conn.execute_script(
                    f"ALTER DATABASE {s.temporal_db} OWNER TO {s.temporal_owner}",
                    database=self._settings.postgres_db,
                )

                self._console.info(
                    f"Ensuring {s.temporal_vis_db} is owned by {s.temporal_owner}"
                )
                conn.execute_script(
                    f"ALTER DATABASE {s.temporal_vis_db} OWNER TO {s.temporal_owner}",
                    database=self._settings.postgres_db,
                )

            self._console.ok("Fixed database and schema ownership")
            return success

        except Exception as e:
            self._console.error(f"Failed to fix ownership: {e}")
            return False

    def verify_password(
        self,
        user: str,
        password: str,
        database: str | None = None,
    ) -> bool:
        """Verify a user can connect with the given password.

        Args:
            user: Username to test
            password: Password to test
            database: Database to connect to

        Returns:
            True if connection succeeds
        """
        s = self._settings
        db = database or s.app_db

        try:
            with psycopg2.connect(
                host=s.host,
                port=s.port,
                dbname=db,
                user=user,
                password=password,
                connect_timeout=5,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            self._console.ok(f"Verified {user} can connect to {db}")
            return True
        except psycopg2.OperationalError as e:
            self._console.error(f"Verification failed for {user}: {e}")
            return False
