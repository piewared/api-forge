"""PostgreSQL connection management for Fly.io deployments.

Provides specialized connection classes for Fly Postgres that handle
proxy tunneling automatically.
"""

from src.infra.flyio.constants import FlyConstants
from src.infra.postgres.connection import DbSettings, PostgresConnection
from src.infra.postgres.local_connection import LocalPostgresConnection


class FlyPostgresConnectionWithProxy(LocalPostgresConnection):
    """PostgreSQL connection for Fly.io using flyctl proxy.

    Connects via localhost on the Fly proxy port with SSL disabled
    (the fly proxy uses WireGuard for encryption).

    NOTE: Port forwarding is managed by the runtime's port_forward() context,
    not by this class.
    """

    def __init__(
        self,
        settings: DbSettings,
        cluster_id: str,
        superuser_mode: bool = False,
    ) -> None:
        self._cluster_id = cluster_id
        super().__init__(
            settings,
            local_port=FlyConstants.PROXY_LOCAL_PORT,
            superuser_mode=superuser_mode,
            ssl_mode="disable",
        )


class FlyPostgresConnection(PostgresConnection):
    """PostgreSQL connection for Fly.io direct connection.

    Used when connecting from within the Fly.io network (e.g., from a
    deployed app) where direct connection is available.
    """

    ...


def get_fly_postgres_connection(
    settings: DbSettings,
    superuser_mode: bool = False,
    cluster_id: str | None = None,
) -> PostgresConnection:
    """Get a Fly.io PostgreSQL connection.

    Args:
        settings: Database settings
        superuser_mode: Whether to connect as superuser
        cluster_id: Fly cluster ID (if provided, uses proxy connection)

    Returns:
        PostgreSQL connection configured for Fly.io
    """
    if cluster_id is not None:
        return FlyPostgresConnectionWithProxy(
            settings=settings,
            cluster_id=cluster_id,
            superuser_mode=superuser_mode,
        )
    else:
        return FlyPostgresConnection(
            settings=settings,
            superuser_mode=superuser_mode,
        )
