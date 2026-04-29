import os
from functools import lru_cache

from loguru import logger
from sqlalchemy import Any

from src.app.runtime.config.config_data import ConfigData
from src.app.runtime.config.config_loader import load_config as _load_config
from src.infra.constants import DEFAULT_PATHS
from src.infra.postgres.connection import DbSettings


def load_raw_config() -> dict[str, Any]:
    """Load configuration from a YAML file.

    Args:
        config_path: Path to the configuration YAML file.

    Returns:
        dict[str, Any]: The unprocessed configuration data.
    """
    from dotenv import load_dotenv

    load_dotenv()
    try:
        # Temporarily disable verbose config loading logs
        logger.disable("src.app.runtime")
        os.environ["APP_ENVIRONMENT"] = "production"

        # Use centralized path to config.yaml
        config_path = DEFAULT_PATHS.config_yaml

        if not config_path.exists():
            msg = f"Could not find config.yaml at {config_path}. Please ensure config.yaml exists in project root."
            raise FileNotFoundError(msg)

        # Load config from the found path
        config = _load_config(file_path=config_path, processed=False)
        config["database"]["environment_mode"] = "production"
    finally:
        logger.enable("src.app.runtime")

    return config


def load_processed_config() -> ConfigData:
    """Load configuration from a YAML file.

    Args:
        config_path: Path to the configuration YAML file.

    Returns:
        ConfigData: The processed configuration data.
    """
    from dotenv import load_dotenv

    load_dotenv()
    try:
        # Temporarily disable verbose config loading logs
        logger.disable("src.app.runtime")
        os.environ["APP_ENVIRONMENT"] = "production"

        # Use centralized path to config.yaml
        config_path = DEFAULT_PATHS.config_yaml

        if not config_path.exists():
            msg = f"Could not find config.yaml at {config_path}. Please ensure config.yaml exists in project root."
            raise FileNotFoundError(msg)

        # Load config from the found path
        config = _load_config(file_path=config_path, processed=True)
        config.database.environment_mode = "production"
    finally:
        logger.enable("src.app.runtime")

    return config


@lru_cache(maxsize=1)
def get_db_settings() -> DbSettings:
    """Get database settings from application config."""
    db_config = load_processed_config().database
    settings = DbSettings.load(db_config)

    return settings
