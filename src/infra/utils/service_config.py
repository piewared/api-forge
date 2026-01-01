"""Service configuration utilities for deployments."""

from typing import cast


def is_redis_enabled() -> bool:
    """Check if Redis is enabled in config.yaml.

    Uses load_config(processed=False) to read raw YAML without environment
    processing, avoiding side effects from loading the full application config.

    Returns:
        True if Redis is enabled, False otherwise
    """
    try:
        from src.app.runtime.config.config_loader import load_config

        # Load raw config without environment variable substitution or processing
        config_data = load_config(processed=False)

        # Navigate to config.redis.enabled in the YAML structure
        config_section = config_data.get("config", {})
        redis_config = config_section.get("redis", {})
        return cast(
            bool, redis_config.get("enabled", True)
        )  # Default to True if not specified

    except Exception:
        # If we can't load config, assume Redis is enabled for backward compatibility
        return True


def is_temporal_enabled() -> bool:
    """Check if Temporal is enabled in config.yaml.

    Uses load_config(processed=False) to read raw YAML without environment
    processing, avoiding side effects from loading the full application config.

    Returns:
        True if Temporal is enabled, False otherwise
    """
    try:
        from src.app.runtime.config.config_loader import load_config

        # Load raw config without environment variable substitution or processing
        config_data = load_config(processed=False)

        # Navigate to config.temporal.enabled in the YAML structure
        config_section = config_data.get("config", {})
        temporal_config = config_section.get("temporal", {})
        return cast(
            bool, temporal_config.get("enabled", True)
        )  # Default to True if not specified

    except Exception:
        # If we can't load config, assume Temporal is enabled for backward compatibility
        return True


def is_bundled_postgres_enabled() -> bool:
    """Check if bundled PostgreSQL is enabled in config.yaml.

    When bundled_postgres.enabled=False, PostgreSQL containers are not deployed
    and the app connects to an external PostgreSQL via DATABASE_URL.

    Uses load_config(processed=False) to read raw YAML without environment
    processing, avoiding side effects from loading the full application config.

    Returns:
        True if bundled PostgreSQL is enabled, False otherwise
    """
    try:
        from src.app.runtime.config.config_loader import load_config

        # Load raw config without environment variable substitution or processing
        config_data = load_config(processed=False)

        # Navigate to config.database.bundled_postgres.enabled in the YAML structure
        config_section = config_data.get("config", {})
        database_config = config_section.get("database", {})
        bundled_postgres = database_config.get("bundled_postgres", {})
        return cast(
            bool, bundled_postgres.get("enabled", True)
        )  # Default to True if not specified

    except Exception:
        # If we can't load config, assume bundled PostgreSQL is enabled
        return True


def get_production_services() -> list[tuple[str, str]]:
    """Get list of production services based on configuration.

    Returns:
        List of (container_name, display_name) tuples for active services
    """
    services: list[tuple[str, str]] = []

    # Add PostgreSQL if bundled postgres is enabled
    if is_bundled_postgres_enabled():
        services.append(("api-forge-postgres", "PostgreSQL"))

    # Add Redis if it's enabled in config
    if is_redis_enabled():
        services.append(("api-forge-redis", "Redis"))

    # Add Temporal services if enabled in config
    if is_temporal_enabled():
        services.append(("api-forge-temporal", "Temporal"))
        services.append(("api-forge-temporal-web", "Temporal Web"))
        services.append(("api-forge-worker", "Temporal Worker"))

    # App is always last (depends on other services)
    services.append(("api-forge-app", "FastAPI App"))

    return services
