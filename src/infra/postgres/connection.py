"""PostgreSQL connection management.

Provides centralized database settings and connection utilities.
"""

import os
from collections.abc import Callable
from functools import lru_cache, wraps
from typing import Any, Literal, Self, TypeVar
from urllib.parse import quote_plus, urlencode

import psycopg2
import psycopg2.extensions
import psycopg2.extras
from pydantic import BaseModel

from src.app.runtime.config.config_data import DatabaseConfig
from src.app.runtime.config.config_loader import load_config
from src.cli.shared.secrets import get_password
from src.infra.constants import DEFAULT_PATHS

# Type variable for function return type
T = TypeVar("T")


class DbSettings(BaseModel):
    """Centralized database settings for CLI operations.

    Extends DatabaseConfig fields with parsed connection details.
    This is the single source of truth for all db CLI commands.
    """

    # From DatabaseConfig
    url: str
    superuser: str
    superuser_password: str | None = None
    app_db: str
    postgres_db: str
    user: str
    password: str | None = None
    owner_user: str
    ro_user: str
    ro_user_password: str | None = None

    # Temporal settings
    temporal_user: str
    temporal_password: str | None = None
    temporal_owner: str
    temporal_db: str = "temporal"
    temporal_vis_db: str = "temporal_visibility"

    # Parsed from URL
    host: str = "localhost"
    port: int = 5432

    def ensure_app_password(self) -> Self:
        """Ensure application user password is set.

        Raises:
            ValueError: If any required password is missing
        """
        if not self.password:
            self.password = get_password(
                f"App user ({self.user}) password: ",
                "POSTGRES_APP_USER_PW",
            )

        return self

    def ensure_ro_user_password(self) -> Self:
        """Ensure read-only user password is set.

        Raises:
            ValueError: If any required password is missing
        """
        if not self.ro_user_password:
            self.ro_user_password = get_password(
                f"Read-only user ({self.ro_user}) password: ",
                "POSTGRES_APP_RO_PW",
            )
        return self

    def ensure_temporal_user_password(self) -> Self:
        """Ensure temporal user password is set.

        Raises:
            ValueError: If any required password is missing
        """
        if not self.temporal_password:
            self.temporal_password = get_password(
                f"Temporal user ({self.temporal_user}) password: ",
                "POSTGRES_TEMPORAL_PW",
            )

        return self

    def ensure_superuser_password(self) -> Self:
        """Ensure superuser password is set.

        Raises:
            ValueError: If superuser password is missing
        """
        if not self.superuser_password:
            self.superuser_password = get_password(
                f"Postgres superuser ({self.superuser}) password: ",
                "POSTGRES_PASSWORD",
            )
        return self

    def ensure_all_passwords(self) -> Self:
        """Ensure all required passwords are set.

        Raises:
            ValueError: If any required password is missing
        """
        self.ensure_superuser_password()
        self.ensure_app_password()
        self.ensure_ro_user_password()
        self.ensure_temporal_user_password()
        return self

    @classmethod
    def load(
        cls,
        db_config: DatabaseConfig,
    ) -> "DbSettings":
        """Load settings from application config.

        Args:
            environment_mode: development or production
            superuser_password: Optional superuser password override

        Returns:
            DbSettings populated from ConfigData.database
        """

        # Parse host/port from URL
        host = db_config.host or "localhost"
        port = db_config.port or 5432

        return cls(
            superuser=db_config.pg_superuser,
            postgres_db=db_config.pg_db,
            temporal_owner=db_config.temporal_owner,
            temporal_user=db_config.temporal_user,
            url=db_config.url,
            app_db=db_config.app_db,
            user=db_config.user,
            owner_user=db_config.owner_user,
            ro_user=db_config.ro_user,
            password=db_config.password,
            host=host,
            port=port,
        )


class PostgresConnection:
    """PostgreSQL connection manager.

    Uses psycopg2 for database operations.
    """

    def __init__(
        self,
        settings: DbSettings,
        superuser_mode: bool = False,
        ssl_mode: Literal["disable", "require"] = "require",
    ):
        """PostgreSQL connection manager.

        Args:
            settings: Database settings
            user: Override user (default: settings.user)
            password: Override password (default: settings.password)
        """
        self._settings = settings
        self._superuser_mode = superuser_mode
        # self._bundled_postgres = bundled_postgres
        # Disable SSL for bundled postgres connections (port-forward scenario)
        # Use 'require' for remote connections to enforce SSL/TLS
        # self._ssl_mode = "disable" if self._bundled_postgres else "require"
        self._ssl_mode = ssl_mode
        self._conn: Any | None = None
        self._current_database: str | None = None  # Track connected database

    def get_dsn(self, database: str | None = None) -> dict[str, Any]:
        """Get connection parameters for psycopg2.connect().

        Args:
            database: Override database name

        Returns:
            Dict of connection parameters
        """

        if self._superuser_mode and not self._settings.superuser_password:
            self._settings.ensure_superuser_password()

        return {
            "host": self._settings.host,
            "port": self._settings.port,
            "dbname": database or self._settings.app_db,
            "user": self._superuser_mode
            and self._settings.superuser
            or self._settings.user,
            "password": self._superuser_mode
            and self._settings.superuser_password
            or self._settings.password
            or "",
            "sslmode": self._ssl_mode,
            "connect_timeout": 5,
        }

    def get_connection_string(self, database: str | None = None) -> str:
        """Get a SQLAlchemy-compatible PostgreSQL connection string.

        This is primarily used for Alembic/SQLAlchemy subprocesses.
        It is derived from `get_dsn()` so it works correctly for bundled,
        external, docker-compose, and port-forwarded connections.

        Returns:
            A URL like: postgresql://user:password@host:port/dbname?sslmode=require
        """

        dsn = self.get_dsn(database)
        user = quote_plus(str(dsn.get("user", "")))
        password = quote_plus(str(dsn.get("password", "")))
        host = str(dsn.get("host", "localhost"))
        port = str(dsn.get("port", "5432"))
        dbname = str(dsn.get("dbname", "postgres"))

        query: dict[str, str] = {}
        sslmode = dsn.get("sslmode")
        if sslmode is not None:
            query["sslmode"] = str(sslmode)
        connect_timeout = dsn.get("connect_timeout")
        if connect_timeout is not None:
            query["connect_timeout"] = str(connect_timeout)

        query_str = urlencode(query) if query else ""
        suffix = f"?{query_str}" if query_str else ""

        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}{suffix}"

    def ensure_connected(self, database: str | None = None) -> Any:
        """Ensure a connection exists, creating one if needed.

        Args:
            database: Override database name

        Returns:
            Active connection
        """
        target_db = database or self._settings.app_db
        # Reconnect if connection is closed or we need a different database
        if (
            self._conn is None
            or self._conn.closed
            or self._current_database != target_db
        ):
            self.close()  # Close existing connection if any
            self._conn = psycopg2.connect(**self.get_dsn(database))
            self._current_database = target_db
        return self._conn

    def connect(self, database: str | None = None) -> Any:
        """Establish a connection to the database.

        Note: Connection is now automatically established on first use.
        This method is provided for explicit connection control.
        """
        self.close()  # Close existing connection if any
        target_db = database or self._settings.app_db
        self._conn = psycopg2.connect(**self.get_dsn(database))
        self._current_database = target_db
        return self._conn

    def close(self) -> None:
        """Close the current connection if open."""
        if self._conn and not self._conn.closed:
            self._conn.close()
        self._conn = None
        self._current_database = None

    def test_connection(self, database: str | None = None) -> tuple[bool, str]:
        """Test database connectivity.

        Creates a separate test connection without affecting the main connection.

        Returns:
            Tuple of (success, message)
        """
        try:
            with psycopg2.connect(**self.get_dsn(database)) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version()")
                    row = cur.fetchone()
                    if row:
                        return True, f"Connected: {row[0]}"
                    return True, "Connected"
        except psycopg2.OperationalError as e:
            print(e)
            return False, f"Connection failed: {e}"
        except Exception as e:
            print(e)
            return False, f"Error: {e}"

    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        database: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute SQL and return results as list of dicts.

        Reuses the persistent connection. Use within a context manager or
        call close() when done to properly cleanup.
        """
        conn = self.ensure_connected(database)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description:
                return [dict(row) for row in cur.fetchall()]
            conn.commit()
            return []

    def execute_script(self, sql: str, database: str | None = None) -> None:
        """Execute a SQL script with autocommit.

        Reuses the persistent connection. Use within a context manager or
        call close() when done to properly cleanup.
        """
        conn = self.ensure_connected(database)
        # Must commit/rollback any pending transaction before changing autocommit
        if conn.status != psycopg2.extensions.STATUS_READY:
            conn.rollback()
        old_autocommit = conn.autocommit
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql)
        finally:
            conn.autocommit = old_autocommit

    def scalar(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        database: str | None = None,
    ) -> Any:
        """Execute SQL and return single scalar value.

        Reuses the persistent connection. Use within a context manager or
        call close() when done to properly cleanup.
        """
        result = self.execute(sql, params, database)
        if result and result[0]:
            return list(result[0].values())[0]
        return None

    @property
    def settings(self) -> DbSettings:
        """Get the database settings."""
        return self._settings

    def __enter__(self) -> "PostgresConnection":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


@lru_cache(maxsize=1)
def get_settings() -> DbSettings:
    """Get database settings from application config."""
    from dotenv import load_dotenv
    from loguru import logger

    load_dotenv()

    try:
        # Temporarily disable verbose config loading logs
        logger.disable("src.app.runtime")
        os.environ["APP_ENVIRONMENT"] = "production"

        # Use centralized path to config.yaml
        config_path = DEFAULT_PATHS.config_yaml

        if not config_path.exists():
            msg = f"Could not find config.yaml at {config_path}. Please ensure config.yaml exists in project root."
            raise FileNotFoundError(msg)

        # Load config from the found path
        config = load_config(file_path=config_path)
        config.database.environment_mode = "production"
        db_config = config.database
        settings = DbSettings.load(db_config)
    finally:
        logger.enable("src.app.runtime")

    return settings


def with_postgres_connection(
    settings: DbSettings | None = None,
    *,
    superuser_mode: bool = False,
    ssl_mode: Literal["disable", "require"] = "require",
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator that provides a PostgresConnection to the decorated function.

    The connection is automatically created and closed. The decorated function
    must accept a 'conn' or 'connection' parameter.

    Args:
        settings: Database settings (if None, will call get_settings())
        superuser_mode: If True, connect as superuser
        ssl_mode: SSL mode for connection (default: require)

    Returns:
        Decorator function

    Example:
        >>> @with_postgres_connection()
        ... def list_users(conn):
        ...     return conn.execute("SELECT * FROM users")
        ...
        >>> users = list_users()  # Connection auto-created and closed

        >>> @with_postgres_connection(superuser_mode=True)
        ... def create_database(conn, db_name: str):
        ...     conn.execute_script(f"CREATE DATABASE {db_name}")
        ...
        >>> create_database("newdb")
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Get settings if not provided
            db_settings = settings if settings is not None else get_settings()

            # Create connection within context manager
            with PostgresConnection(
                settings=db_settings,
                superuser_mode=superuser_mode,
                ssl_mode=ssl_mode,
            ) as conn:
                # Try to pass as keyword argument first
                if "conn" not in kwargs and "connection" not in kwargs:
                    # Check if function signature has 'conn' or 'connection' parameter
                    import inspect

                    sig = inspect.signature(func)
                    if "conn" in sig.parameters:
                        kwargs["conn"] = conn
                    elif "connection" in sig.parameters:
                        kwargs["connection"] = conn
                    else:
                        # Fall back to positional argument
                        args = (conn, *args)

                return func(*args, **kwargs)

        return wrapper

    return decorator
