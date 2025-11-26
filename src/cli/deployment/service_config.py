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


def get_production_services() -> list[tuple[str, str]]:
    """Get list of production services based on configuration.

    Returns:
        List of (container_name, display_name) tuples for active services
    """
    services = [
        ("api-forge-postgres", "PostgreSQL"),
        ("api-forge-temporal", "Temporal"),
        ("api-forge-temporal-web", "Temporal Web"),
        ("api-forge-app", "FastAPI App"),
        ("api-forge-worker", "Temporal Worker"),
    ]

    # Add Redis if it's enabled in config
    if is_redis_enabled():
        services.insert(1, ("api-forge-redis", "Redis"))

    return services
