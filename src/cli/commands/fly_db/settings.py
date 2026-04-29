"""Fly.io database settings, prerequisites, and helpers."""

from dataclasses import dataclass
from hashlib import md5
from urllib.parse import urlparse, urlunparse

from src.app.runtime.config.config_loader import update_env_file
from src.cli.commands.db import DbRuntime, get_fly_runtime
from src.cli.shared.config import load_processed_config, load_raw_config
from src.cli.shared.console import console
from src.infra.flyio import FlyCtlControllerSync


@dataclass
class FlyDbSettings:
    """Settings for Fly.io database creation from config.yaml."""

    name: str
    org: str
    region: str
    vm_memory_mb: int
    vm_cpu_kind: str
    vm_cpus: int
    volume_size_gb: int
    initial_cluster_size: int


def _load_fly_db_settings() -> FlyDbSettings:
    """Load Fly.io database settings from config.yaml.

    Returns:
        FlyDbSettings with values from config.deployments.fly_io
    """

    config = load_processed_config()
    fly_io = config.deployments.fly_io
    db_settings = config.database.settings
    return FlyDbSettings(
        name=fly_io.database.name,
        org=fly_io.org,
        region=fly_io.region,
        vm_memory_mb=fly_io.database.vm_memory_mb,
        vm_cpu_kind=fly_io.database.vm_cpu_kind,
        vm_cpus=fly_io.database.vm_cpus,
        volume_size_gb=db_settings.volume_size_gb,
        initial_cluster_size=db_settings.initial_cluster_size,
    )


def _get_runtime(cluster: str | None = None, *, legacy: bool = False) -> DbRuntime:
    """Return the Fly.io DB runtime.

    Args:
        cluster: Cluster ID or name (for proxy connection)
        legacy: If True, use legacy fly proxy command

    Returns:
        DbRuntime configured for Fly.io
    """
    return get_fly_runtime(cluster, legacy=legacy)


def _generate_default_db_name(settings: FlyDbSettings) -> str:
    """Generate deterministic database name and update .env file.

    Uses MD5 hash of config seed for idempotent name generation.

    Args:
        settings: Fly.io database settings (must have name populated from config)

    Returns:
        Generated database name
    """
    config = load_raw_config()
    generated_name = f"fly-db-{md5(str(config['seed']).encode()).hexdigest()[:8]}"
    update_env_file("FLY_DB_NAME", generated_name)
    return generated_name


def _set_production_database_url(
    db_name: str,
    connection_string: str | None = None,
    *,
    is_managed: bool = False,
) -> str | None:
    """Build production database URL and update .env file.

    For managed postgres, strips password from connection string.
    For unmanaged postgres, builds URL from db name.

    Args:
        db_name: Database/cluster name
        connection_string: Full connection string (for managed postgres)
        is_managed: Whether this is a managed postgres cluster

    Returns:
        The clean URL that was set, or None if failed
    """
    if is_managed and connection_string:
        # Parse and strip password from managed postgres connection string
        parsed = urlparse(connection_string)
        clean_url = urlunparse(
            (
                parsed.scheme,
                f"{parsed.username}@{parsed.hostname}:{parsed.port}"
                if parsed.port
                else f"{parsed.username}@{parsed.hostname}",
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )
    else:
        # Build URL for unmanaged postgres (uses .internal hostname)
        clean_url = f"postgres://postgres@{db_name}.internal:5432/postgres"

    console.info(f"Production connection URL: [dim]{clean_url}[/dim]")
    update_env_file("PRODUCTION_DATABASE_URL", clean_url)
    console.ok("Updated PRODUCTION_DATABASE_URL in .env")
    return clean_url


def _handle_name_collision(
    controller: FlyCtlControllerSync,
    effective_name: str,
    effective_org: str,
    stderr: str,
) -> bool:
    """Handle name collision error by diagnosing if it's user's app or global collision.

    Args:
        controller: Fly.io controller
        effective_name: Name that collided
        effective_org: Organization slug
        stderr: Error message from Fly.io command

    Returns:
        True if the database already exists in user's account (not a global collision)
    """
    if not (
        "Name has already been taken" in stderr
        or "name has already been taken" in stderr
    ):
        return False

    console.print("\n[yellow]Name collision detected. Checking your apps...[/yellow]")

    # List user's apps to help diagnose
    user_apps = controller.apps_list(org=effective_org)
    if user_apps:
        # Check if this name exists in user's apps
        matching_app = next(
            (app for app in user_apps if app.name == effective_name), None
        )

        if matching_app:
            console.print(
                f"\n[green]✓[/green] App '{effective_name}' already exists in your account (org: {matching_app.organization})"
            )
            console.info("This database may have been created previously.")
            console.info(f"Run: api-forge-cli fly db list --org {effective_org}")
            return True
        else:
            console.print(
                f"\n[red]✗[/red] App name '{effective_name}' is taken globally by another Fly.io user."
            )
            console.print("\n[bold]Your apps:[/bold]")
            for app in user_apps[:10]:  # Show first 10
                console.print(f"  • {app.name} (org: {app.organization})")
            if len(user_apps) > 10:
                console.print(f"  ... and {len(user_apps) - 10} more")
            console.info(
                "\nTip: Use --name flag to specify a different name, or set FLY_DB_NAME in .env"
            )
    else:
        console.print("\n[yellow]Could not list your apps.[/yellow]")
        console.info("The name might be taken by another Fly.io user globally.")

    return False
