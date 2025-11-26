"""Configuration template substitution utilities."""

import os
from pathlib import Path
from typing import Any, Literal, overload

import yaml
from loguru import logger
from pydantic_core import ValidationError

from src.app.runtime.config.config_data import ConfigData
from src.app.runtime.config.config_utils import substitute_env_vars

CONFIG_PATH = Path("config.yaml")


@overload
def load_config(file_path: Path = ..., *, processed: None) -> ConfigData: ...


@overload
def load_config(
    file_path: Path = ..., *, processed: Literal[False]
) -> dict[str, Any]: ...


@overload
def load_config(
    file_path: Path = ..., processed: Literal[True] = ...
) -> ConfigData: ...


def load_config(
    file_path: Path = CONFIG_PATH, processed: bool | None = True
) -> ConfigData | dict[str, Any]:
    """
    Load a YAML file with environment variable substitution.

    Args:
        file_path: Path to the YAML file (default: config.yaml)
        processed: Whether to substitute environment variables and validate.
                  - True (default): substitute env vars and validate as ConfigData
                  - False: return raw dict without validation or substitution
                  - None: substitute env vars and validate as ConfigData

    Returns:
        ConfigData if processed is True or None, raw dict if processed is False

    Raises:
        ValueError: If required environment variables are missing, validation fails,
                   or YAML structure is invalid (missing 'config' key)
        FileNotFoundError: If the YAML file doesn't exist

    YAML Structure Requirements:
        The YAML file must have a top-level 'config:' key containing configuration data.

    Side Effects (when processed=True or None):
        - Mutates os.environ by setting environment variables derived from
          {ENV_MODE}_* prefixed variables (e.g., DEVELOPMENT_DATABASE_URL -> DATABASE_URL)
        - Filters out disabled OIDC providers from config.oidc.providers
        - Filters out dev-only OIDC providers in production/test environments
        - Clears Redis password in development environment (dev Redis has no auth)
        - Logs configuration loading details at info/debug level

    Environment-Specific Behavior:
        Reads APP_ENVIRONMENT (default: 'development') and applies overrides from
        environment variables prefixed with the uppercased environment name
        (e.g., PRODUCTION_*, DEVELOPMENT_*, TEST_*).
    """
    with open(file_path) as f:
        content = f.read()

    # Get environment mode
    env_mode = os.getenv("APP_ENVIRONMENT", "development")

    if processed is None:
        processed = True

    # If requested, substitute environment variables in the content
    if processed:
        # Apply environment-specific overrides
        logger.info(f"Loading configuration for environment: {env_mode}")

        # Iterate through all environment variables with the prefix matching the env_mode and return (name, value) pairs of all matching variables
        env_variables = [
            (var, value)
            for var, value in os.environ.items()
            if var.startswith(f"{env_mode.upper()}_")
        ]
        logger.info(f"Applying {len(env_variables)} environment-specific overrides")
        logger.debug(
            f"Override keys: {[var for var, _ in env_variables]}"
        )  # Log keys only

        # Now create new environment variables from the matching variables above by removing the prefix
        for var_name, var_value in env_variables:
            new_var_name = var_name[len(f"{env_mode.upper()}_") :]

            os.environ[new_var_name] = var_value
            logger.debug(f"Set environment variable {new_var_name} from {var_name}")

        # Substitute environment variables
        content = substitute_env_vars(content)

    # Parse YAML
    try:
        loaded: dict[str, Any] = yaml.safe_load(content)
        if not processed:
            return loaded
        if not loaded:
            raise ValueError("Failed to parse YAML")
    except yaml.YAMLError as e:
        raise ValueError(f"Error parsing YAML: {e}") from e

    # Validate and return as ConfigData
    try:
        # Extract the 'config' section from the YAML structure
        if "config" not in loaded:
            raise ValueError("Invalid YAML structure: missing 'config' key")
        config_data = loaded["config"]
        config = ConfigData(**config_data)
    except ValidationError as e:
        raise ValueError(f"Invalid configuration: {e}") from e

    # Remove any OIDC providers that are disabled or use_in_production in non-development environments
    if config.oidc and config.oidc.providers:
        enabled_providers = {}
        for name, provider in config.oidc.providers.items():
            if provider.enabled:
                if provider.dev_only and (
                    env_mode != "development" and env_mode != "test"
                ):
                    logger.info(
                        f"Skipping OIDC provider '{name}' in non-development environment"
                    )
                    continue
                enabled_providers[name] = provider
            else:
                logger.info(f"Skipping disabled OIDC provider '{name}'")

        config.oidc.providers = enabled_providers
        if not config.oidc.providers:
            logger.warning(
                "No OIDC providers are enabled after applying configuration filters"
            )

    # Clear Redis password for development environment (dev Redis has no auth)
    if env_mode == "development" and config.redis and config.redis.password:
        logger.info(
            "Clearing Redis password for development environment (dev Redis has no authentication)"
        )
        config.redis.password = ""

    return config


def _string_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """Custom YAML representer that quotes strings containing special characters or that look like env vars.

    Args:
        dumper: YAML dumper instance
        data: String data to represent

    Returns:
        YAML scalar node with appropriate quoting style
    """
    # Quote strings that contain ${...} patterns or look like numbers
    if "${" in data or data.isdigit():
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
    # Use default representation for other strings
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def save_config(config: ConfigData | dict[str, Any]) -> None:
    """Save the given configuration to a YAML file. In order to do it transactionally,
    it first writes to a temporary file and then renames it to the target path.

    Args:
        config: ConfigData instance or dict to save.

    Note:
        Strings containing ${...} patterns or numeric-looking strings will be
        quoted to preserve their string type when reloaded.
    """
    temp_path = CONFIG_PATH.with_suffix(".tmp")

    # Create a custom dumper with string quoting
    class QuotedDumper(yaml.SafeDumper):
        pass

    QuotedDumper.add_representer(str, _string_representer)

    with open(temp_path, "w") as f:
        serialized = config
        if isinstance(config, ConfigData):
            serialized = config.model_dump()

        yaml.dump(
            serialized,
            f,
            Dumper=QuotedDumper,
            default_flow_style=False,
            sort_keys=False,
            indent=2,
        )
    temp_path.replace(CONFIG_PATH)


# Example usage
if __name__ == "__main__":
    try:
        config_path = Path("config.yaml")

        config = load_config(config_path, processed=True)
        if isinstance(config, ConfigData):
            print("Configuration loaded successfully:")
            print(f"Redis URL: {config.redis.url}")
            print(f"Database URL: {config.database.url}")
            print(f"Keycloak Client ID: {config.oidc.providers['keycloak'].client_id}")
    except ValueError as e:
        print(f"Configuration error: {e}")
    except FileNotFoundError:
        print("config.yaml not found")
