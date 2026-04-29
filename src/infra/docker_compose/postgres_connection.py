from src.infra.postgres.connection import DbSettings, PostgresConnection
from src.infra.postgres.local_connection import LocalPostgresConnection
from src.infra.utils.service_config import is_bundled_postgres_enabled


class DockerComposePostgresConnection(PostgresConnection): ...


def get_docker_compose_postgres_connection(
    settings: DbSettings,
    superuser_mode: bool = False,
) -> PostgresConnection:
    """Get a Docker Compose PostgreSQL connection.

    Args:
        settings: Database settings
        superuser_mode: Whether to connect as superuser

    Returns:
        PostgreSQL connection
    """
    if is_bundled_postgres_enabled():
        return LocalPostgresConnection(
            settings=settings,
            local_port=settings.port,
            superuser_mode=superuser_mode,
            ssl_mode="require",
        )
    else:
        return DockerComposePostgresConnection(
            settings=settings,
            superuser_mode=superuser_mode,
        )
