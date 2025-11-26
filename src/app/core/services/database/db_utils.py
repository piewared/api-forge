from loguru import logger
from sqlalchemy.engine import make_url

from src.app.runtime.config.config_data import ConfigData


# Build the database URL with the resolved password
def get_database_url(config: ConfigData) -> str:
    """Build the database URL with the resolved password from config."""
    base_url = make_url(config.database.url)

    # If the URL already has a password (development mode), use it as-is
    if base_url.password:
        # If in production mode, emit a warning if password is hardcoded
        if config.app.environment == "production":
            logger.warning(
                "Database URL contains a password in production mode; "
                "consider using a secrets file or environment variable."
            )

        return str(base_url)

    # Otherwise, use the resolved password from the computed field
    # Note: The linter incorrectly identifies this as a method, but it's a computed property
    resolved_password = config.database.password
    if resolved_password:
        url_with_password = base_url.set(password=resolved_password)
        # Build the connection string manually to avoid SQLAlchemy's password masking
        return f"postgresql://{url_with_password.username}:{url_with_password.password}@{url_with_password.host}:{url_with_password.port}/{url_with_password.database}"
    else:
        return str(base_url)  # No password available; return URL as-is
