"""Local PostgreSQL connection via localhost (port-forward or direct).

Provides a shared connection class for environments where PostgreSQL
is accessed through a local port — whether via kubectl port-forward,
flyctl proxy, or docker-compose port mapping.
"""

from typing import Any, Literal, override

from src.infra.postgres.connection import DbSettings, PostgresConnection


class LocalPostgresConnection(PostgresConnection):
    """PostgreSQL connection via localhost on a specific local port.

    Used by all environments that access Postgres through a local endpoint:
    - Docker Compose: direct port mapping (e.g., localhost:5432)
    - Fly.io: flyctl proxy tunnel (e.g., localhost:54321)
    - Kubernetes: kubectl port-forward (e.g., localhost:15432)

    Args:
        settings: Database settings
        local_port: The local port to connect on
        superuser_mode: Whether to connect as superuser
        ssl_mode: SSL mode for the connection
    """

    def __init__(
        self,
        settings: DbSettings,
        *,
        local_port: int,
        superuser_mode: bool = False,
        ssl_mode: Literal["disable", "require"] = "disable",
    ) -> None:
        self._local_port = local_port
        super().__init__(settings, superuser_mode=superuser_mode, ssl_mode=ssl_mode)

    @override
    def get_dsn(self, database: str | None = None) -> dict[str, Any]:
        """Get connection parameters targeting localhost on the configured port."""
        if self._superuser_mode and not self._settings.superuser_password:
            self._settings.ensure_superuser_password()

        return {
            "host": "localhost",
            "port": self._local_port,
            "dbname": database or self._settings.app_db,
            "user": (
                self._settings.superuser
                if self._superuser_mode
                else self._settings.user
            ),
            "password": (
                self._settings.superuser_password
                if self._superuser_mode
                else self._settings.password
            )
            or "",
            "sslmode": self._ssl_mode,
            "connect_timeout": 5,
        }
