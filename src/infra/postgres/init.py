"""PostgreSQL database initialization.

Provides database initialization including creating roles, databases,
schemas, and setting up privileges. Used by the CLI `db init` command.
"""

from src.cli.deployment.status_display import is_temporal_enabled
from src.cli.shared.console import console
from src.infra.k8s.helpers import get_namespace, get_postgres_label

from .connection import PostgresConnection

K8S_NAMESPACE = get_namespace()
POSTGRES_LABEL = get_postgres_label()


class PostgresInitializer:
    """Initializes PostgreSQL database with roles, schemas, and privileges."""

    def __init__(self, connection: PostgresConnection) -> None:
        self._connection = connection
        self._settings = connection.settings
        self._console = console

    def initialize(self) -> bool:
        """Initialize the database with roles and schema.

        Returns:
            True if initialization succeeded
        """
        s = self._settings
        s.ensure_all_passwords()
        self._console.print("\n[bold]== Initializing PostgreSQL Database ==[/bold]")

        # Connect as superuser
        conn = self._connection

        success, msg = conn.test_connection(database=self._settings.postgres_db)
        if not success:
            self._console.error(f"Cannot connect to PostgreSQL: {msg}")
            return False

        # Show connected user
        current_user = conn.scalar("SELECT current_user")
        self._console.ok(f"Connected to PostgreSQL as {current_user}")

        try:
            # Create roles
            self._create_role(conn, s.owner_user, login=False)
            self._create_role(conn, s.user, login=True, password=s.password)
            self._create_role(conn, s.ro_user, login=True, password=s.ro_user_password)

            # Create database
            self._create_database(conn, s.app_db, s.owner_user)

            # Set up schema and privileges
            self._setup_schema_and_privileges(conn)

            # Initialize Temporal if enabled
            if is_temporal_enabled() and s.temporal_password:
                self._initialize_temporal(conn, s.temporal_password)

            self._console.ok("Database initialization complete!")
            return True

        except Exception as e:
            self._console.error(f"Initialization failed: {e}")
            return False

    def _create_role(
        self,
        conn: PostgresConnection,
        role_name: str,
        login: bool,
        password: str | None = None,
    ) -> None:
        """Create a role if it doesn't exist."""
        exists = conn.scalar(
            "SELECT COUNT(*) FROM pg_roles WHERE rolname = %s",
            (role_name,),
            database=self._settings.postgres_db,
        )
        if exists:
            self._console.info(f"Role {role_name} already exists")
            if password:
                conn.execute_script(
                    f"ALTER ROLE {role_name} WITH PASSWORD '{password}'",
                    database=self._settings.postgres_db,
                )
                self._console.ok(f"Updated password for {role_name}")
            return

        login_str = "LOGIN" if login else "NOLOGIN"
        password_str = f"PASSWORD '{password}'" if password else ""
        conn.execute_script(
            f"CREATE ROLE {role_name} WITH {login_str} {password_str}",
            database=self._settings.postgres_db,
        )
        self._console.ok(f"Created role {role_name}")

    def _create_database(
        self, conn: PostgresConnection, db_name: str, owner: str
    ) -> None:
        """Create database if it doesn't exist."""
        exists = conn.scalar(
            "SELECT COUNT(*) FROM pg_database WHERE datname = %s",
            (db_name,),
            database=self._settings.postgres_db,
        )
        if exists:
            self._console.info(f"Database {db_name} already exists")
            return

        conn.execute_script(
            f"CREATE DATABASE {db_name} OWNER {owner}",
            database=self._settings.postgres_db,
        )
        self._console.ok(f"Created database {db_name}")

    def _setup_schema_and_privileges(self, conn: PostgresConnection) -> None:
        """Create schema and set up privileges."""
        s = self._settings
        schema = "app"

        # Enable btree_gin extension (required for advanced indexing)
        conn.execute_script(
            "CREATE EXTENSION IF NOT EXISTS btree_gin;",
            database=s.app_db,
        )
        self._console.ok("Enabled btree_gin extension")

        # Create schema (connect to app database)
        schema_exists = conn.scalar(
            "SELECT COUNT(*) FROM pg_namespace WHERE nspname = %s",
            (schema,),
            database=s.app_db,
        )
        if not schema_exists:
            conn.execute_script(
                f"CREATE SCHEMA {schema} AUTHORIZATION {s.owner_user}",
                database=s.app_db,
            )
            self._console.ok(f"Created schema {schema}")
        else:
            self._console.info(f"Schema {schema} already exists")

        # Lock down database and schema (match shell script behavior)
        conn.execute_script(
            f"""
        REVOKE CREATE ON DATABASE {s.app_db} FROM PUBLIC;
        REVOKE ALL ON SCHEMA {schema} FROM PUBLIC;
        """,
            database=s.app_db,
        )

        # Grant privileges (as superuser) - USAGE + CREATE for app user
        conn.execute_script(
            f"""
        GRANT USAGE, CREATE ON SCHEMA {schema} TO {s.user};
        GRANT USAGE ON SCHEMA {schema} TO {s.ro_user};

        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO {s.user};
        GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {s.ro_user};

        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {s.user};
        GRANT SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {s.ro_user};

        GRANT CONNECT ON DATABASE {s.app_db} TO {s.user};
        GRANT CONNECT ON DATABASE {s.app_db} TO {s.ro_user};
        """,
            database=s.app_db,
        )

        # Set default privileges for future objects created by owner role
        conn.execute_script(
            f"""
        ALTER DEFAULT PRIVILEGES FOR ROLE {s.owner_user} IN SCHEMA {schema}
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {s.user};
        ALTER DEFAULT PRIVILEGES FOR ROLE {s.owner_user} IN SCHEMA {schema}
            GRANT SELECT ON TABLES TO {s.ro_user};
        ALTER DEFAULT PRIVILEGES FOR ROLE {s.owner_user} IN SCHEMA {schema}
            GRANT USAGE, SELECT ON SEQUENCES TO {s.user};
        ALTER DEFAULT PRIVILEGES FOR ROLE {s.owner_user} IN SCHEMA {schema}
            GRANT SELECT ON SEQUENCES TO {s.ro_user};
        """,
            database=s.app_db,
        )

        # Set default privileges for future objects created by app user itself
        # (When appuser creates tables directly via SQLModel)
        conn.execute_script(
            f"""
        ALTER DEFAULT PRIVILEGES FOR ROLE {s.user} IN SCHEMA {schema}
            GRANT SELECT ON TABLES TO {s.ro_user};
        ALTER DEFAULT PRIVILEGES FOR ROLE {s.user} IN SCHEMA {schema}
            GRANT SELECT ON SEQUENCES TO {s.ro_user};
        """,
            database=s.app_db,
        )

        self._console.ok(f"Set up privileges for {s.user} and {s.ro_user}")

    def _initialize_temporal(
        self, conn: PostgresConnection, temporal_password: str
    ) -> None:
        """Initialize Temporal database roles and databases.

        Note: Temporal uses the 'public' schema (not custom schemas).
        This matches the behavior of 01-init-app.sh.
        """
        s = self._settings
        self._console.info("Initializing Temporal database...")

        # Create roles
        self._create_role(conn, s.temporal_owner, login=False)
        self._create_role(conn, s.temporal_user, login=True, password=temporal_password)

        # Create databases
        for db in [s.temporal_db, s.temporal_vis_db]:
            self._create_database(conn, db, s.temporal_owner)

        # Configure temporal database
        self._setup_temporal_database(conn, s.temporal_db)

        # Configure temporal_visibility database
        self._setup_temporal_database(conn, s.temporal_vis_db)

        self._console.ok("Set up Temporal database privileges")

    def _setup_temporal_database(self, conn: PostgresConnection, db_name: str) -> None:
        """Set up Temporal database with proper permissions on public schema."""
        s = self._settings

        # Enable btree_gin extension (required for Temporal advanced indexing)
        conn.execute_script(
            "CREATE EXTENSION IF NOT EXISTS btree_gin;",
            database=db_name,
        )
        self._console.ok(f"Enabled btree_gin extension in {db_name}")

        # Lock down database
        conn.execute_script(
            f"""
        REVOKE CREATE ON DATABASE {db_name} FROM PUBLIC;
        """,
            database=db_name,
        )

        # Grant temporal user ability to create and use objects in public schema
        conn.execute_script(
            f"""
        GRANT USAGE, CREATE ON SCHEMA public TO {s.temporal_user};
        """,
            database=db_name,
        )

        # Default privileges for future objects owned by temporal owner
        conn.execute_script(
            f"""
        ALTER DEFAULT PRIVILEGES FOR ROLE {s.temporal_owner} IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLES TO {s.temporal_user};
        ALTER DEFAULT PRIVILEGES FOR ROLE {s.temporal_owner} IN SCHEMA public
            GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {s.temporal_user};
        """,
            database=db_name,
        )

        # Grant privileges on existing objects (if any)
        conn.execute_script(
            f"""
        GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
            ON ALL TABLES IN SCHEMA public TO {s.temporal_user};
        GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {s.temporal_user};
        """,
            database=db_name,
        )

        self._console.ok(f"Configured Temporal database: {db_name}")
