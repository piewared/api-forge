"""PostgreSQL database verification.

Provides verification of PostgreSQL setup including roles, permissions,
and TLS configuration.
"""

from dataclasses import dataclass, field
from enum import Enum

from rich.table import Table

from src.cli.shared.console import console
from src.infra.k8s.helpers import get_namespace, get_postgres_label
from src.infra.utils.service_config import is_temporal_enabled

from .connection import PostgresConnection

K8S_NAMESPACE = get_namespace()
POSTGRES_LABEL = get_postgres_label()


class CheckStatus(Enum):
    """Status of a verification check."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass
class CheckResult:
    """Result of a single verification check."""

    name: str
    status: CheckStatus
    message: str
    details: str | None = None


class PostgresVerifier:
    """Verifies PostgreSQL database setup and configuration."""

    def __init__(self, connection: PostgresConnection) -> None:
        self._settings = connection.settings
        self._connection = connection
        self._console = console
        self._results: list[CheckResult] = field(default_factory=list)

    # Password for connecting (prompted by CLI)
    password: str = ""
    user_name: str = ""

    def _ok(self, name: str, message: str) -> None:
        self._results.append(CheckResult(name, CheckStatus.PASS, message))
        self._console.ok(f"  {message}")

    def _bad(self, name: str, message: str, details: str | None = None) -> None:
        self._results.append(CheckResult(name, CheckStatus.FAIL, message, details))
        self._console.error(f"  {message}")

    def _warn(self, name: str, message: str, details: str | None = None) -> None:
        self._results.append(CheckResult(name, CheckStatus.WARN, message, details))
        self._console.warn(f"  {message}")

    def _skip(self, name: str, message: str) -> None:
        self._results.append(CheckResult(name, CheckStatus.SKIP, message))
        self._console.print(f"[dim]⏭️  {message}[/dim]")

    def verify_all(self) -> bool:
        """Run all verification checks.

        Returns:
            True if all critical checks pass
        """
        self._results = []
        s = self._settings
        s.ensure_superuser_password()

        conn = self._connection

        self._console.print("\n[bold]== Verifying PostgreSQL Configuration ==[/bold]")
        self._console.print(f"   Host: {s.host}:{s.port}")
        self._console.print(f"   DB={s.app_db}  OWNER={s.owner_user}")
        self._console.print(f"   USER={s.user}  RO={s.ro_user}")
        self._console.print()

        # Test connection
        success, msg = conn.test_connection()
        if not success:
            self._bad("connection", f"Cannot connect: {msg}")
            return False
        self._ok("connection", "Connected to PostgreSQL")

        # Run checks
        self._verify_roles(conn)
        self._verify_passwords(conn)
        self._verify_database_ownership(conn)
        self._verify_schema(conn)
        self._verify_schema_permissions(conn)
        self._verify_table_privileges(conn)
        self._verify_tls(conn)

        # Summary
        failed = [r for r in self._results if r.status == CheckStatus.FAIL]
        warnings = [r for r in self._results if r.status == CheckStatus.WARN]

        self._console.print()
        if failed:
            self._console.print(f"[red]❌ {len(failed)} check(s) failed[/red]")
            return False
        if warnings:
            self._console.print(
                f"[yellow]⚠️  Passed with {len(warnings)} warning(s)[/yellow]"
            )
        else:
            self._console.print("[green]✅ All checks passed 🎉[/green]")
        return True

    def _verify_roles(self, conn: PostgresConnection) -> None:
        """Verify database roles exist with correct attributes."""
        s = self._settings
        roles = [
            (s.user, True, "app user"),
            (s.ro_user, True, "read-only user"),
            (s.owner_user, False, "owner role"),
        ]

        if is_temporal_enabled():
            roles.extend(
                [
                    (s.temporal_user, True, "Temporal app user"),
                    (s.temporal_owner, False, "Temporal owner role"),
                ]
            )

        for role_name, should_login, desc in roles:
            count = conn.scalar(
                "SELECT COUNT(*) FROM pg_roles WHERE rolname = %s", (role_name,)
            )
            if not count:
                self._bad(f"role_{role_name}", f"Role {role_name} ({desc}) missing")
                continue

            can_login = conn.scalar(
                "SELECT rolcanlogin FROM pg_roles WHERE rolname = %s", (role_name,)
            )
            login_str = "LOGIN" if should_login else "NOLOGIN"

            if should_login and not can_login:
                self._bad(f"role_{role_name}", f"{role_name} should have LOGIN")
            elif not should_login and can_login:
                self._warn(f"role_{role_name}", f"{role_name} has LOGIN but shouldn't")
            else:
                self._ok(f"role_{role_name}", f"Role {role_name} ({login_str})")

    def _verify_passwords(self, conn: PostgresConnection) -> None:
        """Verify that passwords in local files match what's in the database.

        Attempts to connect as each user role with the password from the local file.
        This ensures the local secrets are in sync with the database.
        """
        s = self._settings

        # Only verify password for roles that should be able to login
        roles_to_test = [
            (s.user, s.password, "app user"),
            (s.ro_user, s.ro_user_password, "read-only user"),
        ]

        if is_temporal_enabled():
            roles_to_test.append(
                (s.temporal_user, s.temporal_password, "Temporal user")
            )

        for role_name, password, desc in roles_to_test:
            if not password:
                self._warn(
                    f"password_{role_name}",
                    f"No password available for {role_name} ({desc}) - skipping password verification",
                )
                continue

            # Try to connect as this user with the password from the local file
            try:
                import psycopg2

                test_conn = conn.get_dsn()
                test_conn["user"] = role_name
                test_conn["password"] = password

                test_conn = psycopg2.connect(**test_conn)
                test_conn.close()

                self._ok(
                    f"password_{role_name}",
                    f"Password verified for {role_name} ({desc})",
                )
            except psycopg2.OperationalError as e:
                if "password authentication failed" in str(e):
                    self._bad(
                        f"password_{role_name}",
                        f"Password mismatch for {role_name} ({desc})",
                        details=(
                            "The password in your local secrets file does not match what's in the database.\n"
                            "Fix: Run 'uv run api-forge-cli k8s db sync' to update database passwords."
                        ),
                    )
                else:
                    self._warn(
                        f"password_{role_name}",
                        f"Could not verify password for {role_name}: {e}",
                    )
            except Exception as e:
                self._warn(
                    f"password_{role_name}",
                    f"Unexpected error verifying password for {role_name}: {e}",
                )

    def _verify_database_ownership(self, conn: PostgresConnection) -> None:
        """Verify database ownership."""
        s = self._settings
        owner = conn.scalar(
            """
            SELECT pg_catalog.pg_get_userbyid(d.datdba)
            FROM pg_catalog.pg_database d WHERE d.datname = %s
            """,
            (s.app_db,),
        )
        if not owner:
            self._bad("db_ownership", f"Database {s.app_db} does not exist")
        elif owner != s.owner_user:
            self._bad(
                "db_ownership", f"{s.app_db} owned by {owner}, expected {s.owner_user}"
            )
        else:
            self._ok("db_ownership", f"Database {s.app_db} owned by {s.owner_user}")

    def _verify_schema(self, conn: PostgresConnection) -> None:
        """Verify schema ownership."""
        s = self._settings
        schema = "app"
        owner = conn.scalar(
            "SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = %s",
            (schema,),
            s.app_db,
        )
        if not owner:
            self._bad("schema", f"Schema {schema} does not exist")
        elif owner != s.owner_user:
            self._warn(
                "schema", f"Schema {schema} owned by {owner}, expected {s.owner_user}"
            )
        else:
            self._ok("schema", f"Schema {schema} owned by {s.owner_user}")

    def _verify_schema_permissions(self, conn: PostgresConnection) -> None:
        """Verify schema-level permissions for users."""
        s = self._settings

        # Check app user permissions on app schema
        self._check_schema_user_permissions(
            conn, s.user, "app", s.app_db, usage=True, create=True, desc="app user"
        )

        # Check if Temporal is enabled
        # Note: Temporal uses the 'public' schema, not custom schemas
        if is_temporal_enabled():
            # Check temporal user permissions on public schema in temporal databases
            # Each database has its own public schema with separate permissions
            self._check_schema_user_permissions(
                conn,
                s.temporal_user,
                "public",
                s.temporal_db,
                usage=True,
                create=True,
                desc=f"Temporal user on {s.temporal_db}.public",
            )
            self._check_schema_user_permissions(
                conn,
                s.temporal_user,
                "public",
                s.temporal_vis_db,
                usage=True,
                create=True,
                desc=f"Temporal user on {s.temporal_vis_db}.public",
            )

    def _check_schema_user_permissions(
        self,
        conn: PostgresConnection,
        user: str,
        schema: str,
        database: str,
        usage: bool,
        create: bool,
        desc: str,
    ) -> None:
        """Check specific user permissions on a schema.

        Args:
            conn: Database connection
            user: Username to check permissions for
            schema: Schema name
            database: Database name containing the schema
            usage: Whether USAGE permission is expected
            create: Whether CREATE permission is expected
            desc: Description for logging
        """
        # Check if schema exists
        schema_exists = conn.scalar(
            "SELECT COUNT(*) FROM pg_namespace WHERE nspname = %s",
            (schema,),
            database,
        )

        if not schema_exists:
            self._bad(
                f"schema_perms_{user}_{schema}",
                f"Schema {schema} does not exist in {database}",
            )
            return

        # Check USAGE privilege
        has_usage = conn.scalar(
            "SELECT has_schema_privilege(%s, %s, 'USAGE')",
            (user, schema),
            database,
        )

        # Check CREATE privilege
        has_create = conn.scalar(
            "SELECT has_schema_privilege(%s, %s, 'CREATE')",
            (user, schema),
            database,
        )

        issues = []
        if usage and not has_usage:
            issues.append("USAGE")
        if create and not has_create:
            issues.append("CREATE")

        if issues:
            self._bad(
                f"schema_perms_{user}_{schema}",
                f"{desc} missing {', '.join(issues)} on schema {schema} in {database}",
            )
        else:
            perms = []
            if has_usage:
                perms.append("USAGE")
            if has_create:
                perms.append("CREATE")
            self._ok(
                f"schema_perms_{user}_{schema}",
                f"{desc} has {', '.join(perms)} on schema {schema}",
            )

    def _verify_table_privileges(self, conn: PostgresConnection) -> None:
        """Verify table privileges."""
        s = self._settings
        schema = "app"

        table_count = conn.scalar(
            "SELECT COUNT(*) FROM pg_tables WHERE schemaname = %s",
            (schema,),
            s.app_db,
        )
        if not table_count:
            self._skip(
                "table_privileges",
                f"No tables in schema {schema} (created when app runs)",
            )
            return

        has_privs = conn.scalar(
            """
            SELECT COUNT(*) FROM information_schema.table_privileges
            WHERE grantee = %s AND table_schema = %s AND privilege_type = 'SELECT'
            """,
            (s.user, schema),
            s.app_db,
        )
        if has_privs:
            self._ok("table_privileges", f"{s.user} has table privileges")
        else:
            self._warn("table_privileges", f"{s.user} may be missing privileges")

    def _verify_tls(self, conn: PostgresConnection) -> None:
        """Verify TLS configuration."""
        ssl_mode = conn.scalar("SHOW ssl")
        if ssl_mode == "on":
            self._ok("tls", "SSL is enabled")
        else:
            self._warn("tls", f"SSL is {ssl_mode} (expected 'on' for production)")

    def print_summary(self) -> None:
        """Print summary table of results."""
        table = Table(title="Verification Summary")
        table.add_column("Check", style="cyan")
        table.add_column("Status")
        table.add_column("Message")

        status_map = {
            CheckStatus.PASS: "[green]✅ PASS[/green]",
            CheckStatus.FAIL: "[red]❌ FAIL[/red]",
            CheckStatus.WARN: "[yellow]⚠️  WARN[/yellow]",
            CheckStatus.SKIP: "[dim]⏭️  SKIP[/dim]",
        }

        for r in self._results:
            table.add_row(r.name, status_map[r.status], r.message)

        self._console.print(table)
