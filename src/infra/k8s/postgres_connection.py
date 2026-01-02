from typing import Any, override

from src.infra.constants import DEFAULT_CONSTANTS
from src.infra.k8s.helpers import get_namespace, get_postgres_label
from src.infra.k8s.port_forward import with_postgres_port_forward
from src.infra.postgres.connection import DbSettings, PostgresConnection
from src.infra.utils.service_config import is_bundled_postgres_enabled

K8S_NAMESPACE = get_namespace()
POSTGRES_LABEL = get_postgres_label()


class K8sPostgresConnectionBundled(PostgresConnection):
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
            ssl_mode="disable",
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
            "port": DEFAULT_CONSTANTS.DEFAULT_EPHEMERAL_PORT,
            "dbname": database or self._settings.app_db,
            "user": self._superuser_mode
            and self._settings.superuser
            or self._settings.user,
            "password": self._superuser_mode
            and self._settings.superuser_password
            or self._settings.password,
            "sslmode": self._ssl_mode,
        }

    @override
    @with_postgres_port_forward(namespace=K8S_NAMESPACE, pod_label=POSTGRES_LABEL)
    def test_connection(self, database: str | None = None) -> tuple[bool, str]:
        return super().test_connection(database)

    @override
    @with_postgres_port_forward(namespace=K8S_NAMESPACE, pod_label=POSTGRES_LABEL)
    def connect(self, database: str | None = None) -> Any:
        return super().connect(database)

    @override
    @with_postgres_port_forward(namespace=K8S_NAMESPACE, pod_label=POSTGRES_LABEL)
    def execute(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        database: str | None = None,
    ) -> list[dict[str, Any]]:
        return super().execute(sql, params, database)

    @override
    @with_postgres_port_forward(namespace=K8S_NAMESPACE, pod_label=POSTGRES_LABEL)
    def execute_script(self, sql: str, database: str | None = None) -> None:
        return super().execute_script(sql, database)

    @override
    @with_postgres_port_forward(namespace=K8S_NAMESPACE, pod_label=POSTGRES_LABEL)
    def scalar(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        database: str | None = None,
    ) -> Any:
        return super().scalar(sql, params, database)


class K8sPostgresConnection(PostgresConnection): ...


def get_k8s_postgres_connection(
    settings: DbSettings,
    superuser_mode: bool = False,
) -> PostgresConnection:
    """Get a Kubernetes PostgreSQL connection.

    Args:
        settings: Database settings
        superuser_mode: Whether to connect as superuser
        bundled_postgres: Whether to use bundled Postgres (port-forward)

    Returns:
        PostgreSQL connection
    """
    if is_bundled_postgres_enabled():
        return K8sPostgresConnectionBundled(
            settings=settings,
            superuser_mode=superuser_mode,
        )
    else:
        return K8sPostgresConnection(
            settings=settings,
            superuser_mode=superuser_mode,
        )
