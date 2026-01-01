"""PostgreSQL database reset functionality.

Provides database-level reset operations to return PostgreSQL to a clean state.
This drops all databases, roles, and schemas created by the application.
"""

from src.cli.shared.console import console
from src.infra.k8s.helpers import get_namespace, get_postgres_label
from src.infra.k8s.port_forward import with_postgres_port_forward_if_needed

from .connection import PostgresConnection

K8S_NAMESPACE = get_namespace()
POSTGRES_LABEL = get_postgres_label()


class PostgresReset:
    """Resets PostgreSQL database to clean state.

    This includes:
    - Dropping application databases
    - Dropping application roles
    - Dropping application schemas
    - Preserving system databases and roles
    """

    def __init__(self, connection: PostgresConnection) -> None:
        self._connection = connection
        self._settings = connection.settings
        self._console = console

    @with_postgres_port_forward_if_needed(
        namespace=K8S_NAMESPACE, pod_label=POSTGRES_LABEL
    )
    def reset(self, include_temporal: bool = True) -> bool:
        """Reset the PostgreSQL database to clean state.

        Drops all application-created databases, roles, and schemas.

        Args:
            superuser_password: Password for superuser connection
            include_temporal: Whether to drop Temporal databases/roles

        Returns:
            True if reset succeeded, False otherwise
        """
        self._console.print("\n[bold]== PostgreSQL Database Reset ==[/bold]")

        try:
            # Connect as superuser to postgres database
            self._settings.ensure_superuser_password()
            conn = self._connection

            # Test connection
            success, msg = conn.test_connection(database="postgres")
            if not success:
                self._console.error(f"Cannot connect to PostgreSQL: {msg}")
                return False

            self._console.ok("Connected to PostgreSQL as superuser")

            # Terminate connections to databases we're about to drop
            self._terminate_connections(conn, include_temporal)

            # Drop application database
            self._drop_database(conn, self._settings.app_db)

            # Drop Temporal databases if requested
            if include_temporal:
                self._drop_database(conn, self._settings.temporal_db)
                self._drop_database(conn, self._settings.temporal_vis_db)

            # Drop application roles
            self._drop_role(conn, self._settings.user)
            self._drop_role(conn, self._settings.ro_user)
            self._drop_role(conn, self._settings.owner_user)

            # Drop Temporal roles if requested
            if include_temporal:
                self._drop_role(conn, self._settings.temporal_user)
                self._drop_role(conn, self._settings.temporal_owner)

            self._console.ok("PostgreSQL database reset complete!")
            return True

        except Exception as e:
            self._console.error(f"Reset failed: {e}")
            return False

    def _terminate_connections(
        self, conn: PostgresConnection, include_temporal: bool
    ) -> None:
        """Terminate all connections to application databases."""
        s = self._settings
        databases = [s.app_db]

        if include_temporal:
            databases.extend([s.temporal_db, s.temporal_vis_db])

        for db in databases:
            try:
                conn.execute_script(
                    f"""
                    SELECT pg_terminate_backend(pg_stat_activity.pid)
                    FROM pg_stat_activity
                    WHERE pg_stat_activity.datname = '{db}'
                      AND pid <> pg_backend_pid();
                    """,
                    database="postgres",
                )
                self._console.info(f"Terminated connections to {db}")
            except Exception:
                # Database might not exist, ignore
                pass

    def _drop_database(self, conn: PostgresConnection, db_name: str) -> None:
        """Drop a database if it exists."""
        try:
            exists = conn.scalar(
                "SELECT COUNT(*) FROM pg_database WHERE datname = %s",
                (db_name,),
                database="postgres",
            )

            if exists:
                # Terminate connections using a DO block to avoid SELECT result issues
                conn.execute_script(
                    f"""
                    DO $$
                    DECLARE
                        r RECORD;
                    BEGIN
                        FOR r IN
                            SELECT pid FROM pg_stat_activity
                            WHERE datname = '{db_name}' AND pid <> pg_backend_pid()
                        LOOP
                            PERFORM pg_terminate_backend(r.pid);
                        END LOOP;
                    END $$;
                    """,
                    database="postgres",
                )

                # Drop database (already in autocommit mode via execute_script)
                conn.execute_script(
                    f"DROP DATABASE IF EXISTS {db_name}", database="postgres"
                )
                self._console.ok(f"Dropped database: {db_name}")
            else:
                self._console.info(f"Database {db_name} does not exist")

        except Exception as e:
            self._console.warn(f"Could not drop database {db_name}: {e}")

    def _drop_role(self, conn: PostgresConnection, role_name: str) -> None:
        """Drop a role if it exists."""
        try:
            exists = conn.scalar(
                "SELECT COUNT(*) FROM pg_roles WHERE rolname = %s",
                (role_name,),
                database="postgres",
            )

            if exists:
                # Reassign owned objects and drop role
                conn.execute_script(
                    f"""
                    REASSIGN OWNED BY {role_name} TO {self._settings.superuser};
                    DROP OWNED BY {role_name};
                    DROP ROLE IF EXISTS {role_name};
                    """,
                    database="postgres",
                )
                self._console.ok(f"Dropped role: {role_name}")
            else:
                self._console.info(f"Role {role_name} does not exist")

        except Exception as e:
            self._console.warn(f"Could not drop role {role_name}: {e}")
