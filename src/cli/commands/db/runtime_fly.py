"""Fly.io runtime for database workflows."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from functools import lru_cache
from typing import Any

from src.cli.commands.db.runtime import DbRuntime
from src.cli.shared.config import get_db_settings
from src.cli.shared.console import console
from src.infra.flyio import fly_postgres_port_forward_if_needed
from src.infra.flyio.constants import FlyConstants
from src.infra.flyio.db_settings import FlyDbSettings
from src.infra.flyio.postgres_connection import (
    FlyPostgresConnectionWithProxy,
    get_fly_postgres_connection,
)
from src.infra.postgres.connection import DbSettings
from src.infra.secrets import get_secrets_manager


def _is_fly_temporal_enabled() -> bool:
    """Check if Temporal is enabled for Fly.io deployment.

    Currently Temporal is not supported on Fly.io.
    """
    return False


def _is_fly_bundled_postgres_enabled() -> bool:
    """Check if bundled (self-managed) Postgres is enabled.

    Returns True if using Fly Postgres (legacy) instead of MPG.
    """
    # TODO: Read from config.yaml fly.postgres.bundled setting
    return False


def _get_fly_deployer() -> None:
    """Get the Fly.io deployer.

    Returns None as Fly.io doesn't use Helm-style deployment.
    """
    return None


def _create_fly_db_settings_factory(
    cluster_id: str | None, is_managed: bool
) -> Callable[[], DbSettings]:
    """Create a cached settings factory for Fly.io.

    Args:
        cluster_id: Fly cluster ID
        is_managed: True for Fly MPG, False for legacy Fly Postgres

    Returns:
        LRU-cached function that returns FlyDbSettings
    """

    @lru_cache(maxsize=1)
    def _get_fly_db_settings() -> DbSettings:
        """Get Fly.io database settings with auto password retrieval.

        Returns FlyDbSettings which knows how to retrieve the superuser
        password from Fly (MPG connection string or SSH for legacy).
        """
        # Get base settings from config
        base_settings = get_db_settings()

        # Create FlyDbSettings with Fly-specific fields
        return FlyDbSettings(
            # Copy all fields from base settings
            url=base_settings.url,
            superuser=base_settings.superuser,
            superuser_password=base_settings.superuser_password,
            app_db=base_settings.app_db,
            postgres_db=base_settings.postgres_db,
            user=base_settings.user,
            password=base_settings.password,
            owner_user=base_settings.owner_user,
            ro_user=base_settings.ro_user,
            ro_user_password=base_settings.ro_user_password,
            temporal_user=base_settings.temporal_user,
            temporal_password=base_settings.temporal_password,
            temporal_owner=base_settings.temporal_owner,
            temporal_db=base_settings.temporal_db,
            temporal_vis_db=base_settings.temporal_vis_db,
            host=base_settings.host,
            port=base_settings.port,
            # Fly-specific fields
            is_managed=is_managed,
            cluster_id=cluster_id,
        )

    return _get_fly_db_settings


def get_fly_runtime(
    cluster_id: str | None = None, *, legacy: bool = False
) -> DbRuntime:
    """Build a DbRuntime for Fly.io workflows.

    Args:
        cluster_id: Optional Fly Managed Postgres cluster ID.
                   If provided, connections will use the fly proxy tunnel.
                   If not provided, commands will use direct connection.
        legacy: If True, use legacy `fly proxy` command instead of `fly mpg proxy`
                This also indicates unmanaged Fly Postgres vs managed MPG.

    Returns:
        DbRuntime configured for Fly.io
    """
    # Create settings factory with Fly-specific configuration
    # is_managed is the opposite of legacy
    settings_factory = _create_fly_db_settings_factory(
        cluster_id=cluster_id,
        is_managed=not legacy,
    )

    def _port_forward() -> AbstractContextManager[None]:
        """Return a context manager for Fly port forwarding.

        Uses fly_postgres_port_forward_if_needed which:
        - Sets up flyctl proxy when cluster_id is provided
        - Does nothing when cluster_id is None (assumes direct connection)

        This mirrors the k8s pattern of postgres_port_forward_if_needed.
        """
        return fly_postgres_port_forward_if_needed(
            cluster_id=cluster_id,
            local_port=FlyConstants.PROXY_LOCAL_PORT,
            timeout=FlyConstants.PROXY_STARTUP_TIMEOUT,
            legacy=legacy,
        )

    return DbRuntime(
        name="fly",
        console=console,
        get_settings=settings_factory,
        connect=lambda settings, superuser: get_fly_postgres_connection(
            settings, superuser_mode=superuser, cluster_id=cluster_id
        ),
        port_forward=_port_forward,
        get_deployer=_get_fly_deployer,
        secrets_manager=get_secrets_manager(),
        is_temporal_enabled=_is_fly_temporal_enabled,
        is_bundled_postgres_enabled=_is_fly_bundled_postgres_enabled,
    )


def run_sync_fly(
    runtime: DbRuntime,
    settings: FlyDbSettings,
    cluster_id: str,
    *,
    legacy: bool = False,
    controller: Any = None,
) -> bool:
    """Synchronize PostgreSQL role passwords for a Fly.io cluster.

    Orchestrates the full password sync workflow:
    1. Retrieves superuser password from Fly
    2. Connects via port forward and syncs app role passwords
    3. For unmanaged: pushes local superuser password to Fly secrets
    4. For managed: pulls Fly's superuser password to local secrets

    Args:
        runtime: The Fly DbRuntime (for PostgresPasswordSync)
        settings: FlyDbSettings with cluster configuration
        cluster_id: Fly cluster ID for port forwarding
        legacy: If True, use legacy fly proxy
        controller: FlyCtlControllerSync (for secrets_set on unmanaged)

    Returns:
        True if sync succeeded, False otherwise
    """
    from src.infra.postgres import PostgresPasswordSync

    is_managed = settings.is_superuser_password_managed_by_fly

    # Step 1: Retrieve superuser password from Fly
    console.info("Retrieving current superuser password from Fly...")
    try:
        settings.ensure_superuser_password()
        console.ok(
            f"Retrieved superuser password from Fly {'MPG' if is_managed else 'postgres app'}"
        )
    except RuntimeError as e:
        console.error(f"Failed to retrieve superuser password: {e}")
        if not is_managed:
            console.info(f"Make sure the app is running: fly status -a {cluster_id}")
        return False

    # Step 2: For unmanaged, also need local password (target for DB update)
    local_superuser_password: str | None = None
    if not is_managed:
        try:
            local_superuser_password = settings.get_local_superuser_password()
        except KeyError as e:
            console.error(f"Failed to read local superuser password: {e}")
            console.info("Ensure postgres_password.txt exists in infra/secrets/keys/")
            return False

    # Step 3: Connect and sync passwords
    console.info("Connecting to database...")
    with fly_postgres_port_forward_if_needed(
        cluster_id=cluster_id,
        local_port=FlyConstants.PROXY_LOCAL_PORT,
        timeout=FlyConstants.PROXY_STARTUP_TIMEOUT,
        legacy=legacy,
    ):
        conn = FlyPostgresConnectionWithProxy(
            settings=settings,
            cluster_id=cluster_id,
            superuser_mode=True,
        )

        success = True
        with conn:
            # Sync app user passwords (same for both managed and unmanaged)
            console.print_subheader("Syncing app role passwords (local -> DB)")
            sync_tool = PostgresPasswordSync(
                runtime=runtime,
                connection=conn,
            )
            success = sync_tool.sync_user_roles_and_passwords()

            # Superuser sync differs by type
            if success and not is_managed:
                console.print_subheader("Syncing superuser password (local -> DB)")
                assert local_superuser_password is not None
                try:
                    conn.execute_script(
                        f"ALTER USER postgres PASSWORD '{local_superuser_password}'",
                        database=settings.postgres_db,
                    )
                    console.ok("Updated postgres superuser password in database")
                except Exception as e:
                    console.error(f"Failed to update superuser password: {e}")
                    success = False

    if not success:
        return False

    # Step 4: Post-DB sync — update external secrets
    if not is_managed:
        console.print_subheader("Syncing Fly secrets (local -> Fly)")
        assert local_superuser_password is not None
        assert controller is not None
        result = controller.secrets_set(
            cluster_id,
            {"OPERATOR_PASSWORD": local_superuser_password},
            stage=False,
        )
        if result.success:
            console.ok("Updated OPERATOR_PASSWORD secret in Fly")
            console.info(
                "Note: The postgres app will restart to pick up the new secret"
            )
        else:
            console.warn(
                f"Failed to update Fly secret: {result.stderr or 'Unknown error'}"
            )
            console.info(
                f"You may need to run: fly secrets set OPERATOR_PASSWORD=<password> -a {cluster_id}"
            )
    else:
        console.print_subheader("Syncing superuser password (Fly -> local)")
        try:
            secrets_file = settings.sync_superuser_password_to_local()
            console.ok(f"Updated local secrets file: {secrets_file}")
            console.info("Fly manages MPG superuser - local file synced to match")
        except Exception as e:
            console.error(f"Failed to sync superuser password to local: {e}")
            return False

    console.ok("Password sync completed")
    return True
