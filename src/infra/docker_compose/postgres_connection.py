from typing import Any, override

from src.infra.postgres.connection import DbSettings, PostgresConnection
from src.infra.utils.service_config import is_bundled_postgres_enabled


class DockerComposePostgresConnectionBundled(PostgresConnection):
    def __init__(
        self,
        settings: DbSettings,
        superuser_mode: bool = False,
    ) -> None:
        """PostgreSQL connection manager for bundled Postgres.
        Args:
            settings: Database settings
            user: Override user (default: settings.user)
            password: Override password (default: settings.password)
        """
        super().__init__(
            settings,
            superuser_mode=superuser_mode,
            ssl_mode="require",
        )

    @override
    def get_dsn(self, database: str | None = None) -> dict[str, Any]:
        """Get connection parameters for psycopg2.connect().

        Args:
            database: Override database name

        Returns:
            Dict of connection parameters
        """
        return {
            "host": "localhost",
            "port": self._settings.port,
            "dbname": database or self._settings.app_db,
            "user": self._superuser_mode
            and self._settings.superuser
            or self._settings.user,
            "password": self._superuser_mode
            and self._settings.superuser_password
            or self._settings.password,
            "sslmode": self._ssl_mode,
        }


class DockerComposePostgresConnection(PostgresConnection): ...


def get_docker_compose_postgres_connection(
    settings: DbSettings,
    superuser_mode: bool = False,
) -> PostgresConnection:
    """Get a Docker Compose PostgreSQL connection.
    Args:
        settings: Database settings
        superuser_mode: Whether to connect as superuser
        bundled_postgres: Whether to use bundled Postgres (port-forward)

    Returns:
        PostgreSQL connection
    """
    if is_bundled_postgres_enabled():
        return DockerComposePostgresConnectionBundled(
            settings=settings,
            superuser_mode=superuser_mode,
        )
    else:
        return DockerComposePostgresConnection(
            settings=settings,
            superuser_mode=superuser_mode,
        )
