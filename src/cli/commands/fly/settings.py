"""Fly.io app settings, prerequisites, and config helpers."""

from dataclasses import dataclass
from hashlib import md5

from src.cli.shared.config import load_processed_config, load_raw_config
from src.cli.shared.env_file import parse_env_file
from src.utils.paths import get_project_root


@dataclass
class FlyAppSettings:
    """Settings for Fly.io app deployment from config.yaml."""

    name: str
    org: str
    region: str


def _load_fly_app_settings() -> FlyAppSettings:
    """Load Fly.io app settings from config.yaml.

    Returns:
        FlyAppSettings with values from config.deployments.fly_io
    """
    config = load_processed_config()
    fly_io = config.deployments.fly_io
    return FlyAppSettings(
        name=fly_io.app.name,
        org=fly_io.org,
        region=fly_io.region,
    )


def _generate_default_app_name() -> str:
    """Generate deterministic app name and update .env file.

    Uses MD5 hash of config seed for idempotent name generation.

    Returns:
        Generated app name (e.g., 'fly-app-a1b2c3d4')
    """
    from src.app.runtime.config.config_loader import update_env_file

    config = load_raw_config()
    generated_name = f"fly-app-{md5(str(config['seed']).encode()).hexdigest()[:8]}"
    update_env_file("FLY_APP_NAME", generated_name)
    return generated_name


def _get_app_name(
    app: str | None,
    settings: FlyAppSettings,
) -> str:
    """Get effective app name from argument, settings, or generate one.

    Args:
        app: Explicitly provided app name
        settings: Settings loaded from config

    Returns:
        Effective app name to use
    """
    if app:
        return app
    if settings.name and not _is_placeholder_name(settings.name):
        return settings.name
    return _generate_default_app_name()


def _is_placeholder_name(name: str) -> bool:
    """Check if a name looks like a placeholder that should be replaced.

    Args:
        name: The app name to check

    Returns:
        True if the name appears to be a placeholder
    """
    placeholders = [
        "your-",
        "my-app",
        "example",
        "placeholder",
        "changeme",
        "todo",
    ]
    name_lower = name.lower()
    return any(p in name_lower for p in placeholders)


def _check_service_enabled(service: str) -> bool:
    """Check if a service is enabled in config.yaml.

    Args:
        service: Service name ('redis', 'temporal')

    Returns:
        True if the service is enabled
    """
    config = load_processed_config()
    if service == "redis":
        return config.redis.enabled
    elif service == "temporal":
        return config.temporal.enabled
    return False


def _get_db_cluster_name() -> str | None:
    """Get the configured database cluster name from config.yaml."""
    config = load_processed_config()
    return config.deployments.fly_io.database.name or None


def _load_env_file(*, include_fly_overrides: bool = False) -> dict[str, str]:
    """Load environment variables from .env, with optional Fly.io overlay.

    Args:
        include_fly_overrides: If True, layer .env.fly on top of .env
            so that Fly.io-specific values (e.g. internal DB URL) win.

    Returns:
        Dictionary of environment variable name -> value.
    """
    env_path = get_project_root() / ".env"
    env_vars = parse_env_file(env_path) if env_path.exists() else {}

    if include_fly_overrides:
        fly_path = get_project_root() / ".env.fly"
        if fly_path.exists():
            env_vars.update(parse_env_file(fly_path))

    return env_vars
