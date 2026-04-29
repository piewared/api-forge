"""Configuration template substitution utilities."""

import os
import re
from pathlib import Path
from typing import Any, Literal, overload

import yaml  # type: ignore[import-untyped]
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

        # Promote prefixed env vars (e.g. PRODUCTION_DATABASE_URL -> DATABASE_URL)
        from src.app.runtime.config.env_promotion import promote_env_vars

        promoted = promote_env_vars(dict(os.environ), env_mode)
        override_count = 0
        for key, value in promoted.items():
            if key not in os.environ or os.environ[key] != value:
                os.environ[key] = value
                logger.debug(f"Promoted environment variable {key}")
                override_count += 1
        logger.info(f"Applying {override_count} environment-specific overrides")

        # Substitute environment variables
        content = substitute_env_vars(content)

    # Parse YAML
    try:
        loaded: dict[str, Any] = yaml.safe_load(content)
        if not loaded:
            raise ValueError("Failed to parse YAML")

        # Extract the 'config' section from the YAML structure
        if "config" not in loaded:
            raise ValueError("Invalid YAML structure: missing 'config' key")

        config_data = loaded["config"]
        if not processed:
            return config_data

    except yaml.YAMLError as e:
        raise ValueError(f"Error parsing YAML: {e}") from e

    # Validate and return as ConfigData
    try:
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
    if env_mode == "development" and config.redis:
        logger.info(
            "Clearing Redis password for development environment (dev Redis has no authentication)"
        )
        config.redis.password = ""
        config.redis.password_file_path = None
        config.redis.password_env_var = None

    return config


def _string_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """Custom YAML representer that quotes strings containing special characters or that look like env vars.

    Args:
        dumper: YAML dumper instance
        data: String data to represent

    Returns:
        YAML scalar node with appropriate quoting style
    """
    # Quote strings that contain ${...} patterns, look like numbers, or are empty
    if "${" in data or data.isdigit() or data == "":
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
            {"config": serialized},
            f,
            Dumper=QuotedDumper,
            default_flow_style=False,
            sort_keys=False,
            indent=2,
        )
    temp_path.replace(CONFIG_PATH)


def update_env_file(
    var_name: str, value: str, env_file_path: Path = Path(".env")
) -> None:
    """Update an environment variable in the .env file and load it into os.environ.

    Uses regex to find and replace the variable in the .env file. If the variable
    doesn't exist, it will be appended to the file.

    Args:
        var_name: Name of the environment variable (e.g., "FLY_DB_NAME")
        value: New value for the variable
        env_file_path: Path to .env file (default: .env in current directory)

    Raises:
        FileNotFoundError: If .env file doesn't exist

    Example:
        >>> update_env_file("FLY_DB_NAME", "my-database-123")
        # .env file now contains: FLY_DB_NAME=my-database-123
        # os.environ["FLY_DB_NAME"] is now set to "my-database-123"
    """
    if not env_file_path.exists():
        raise FileNotFoundError(f".env file not found at {env_file_path}")

    # Read current .env contents
    with open(env_file_path) as f:
        env_contents = f.read()

    # Regex pattern to match the variable (handles quoted and unquoted values)
    pattern = rf"^{re.escape(var_name)}=.*$"
    replacement = f"{var_name}={value}"

    # Check if variable exists
    if re.search(pattern, env_contents, re.MULTILINE):
        # Update existing variable
        env_contents = re.sub(pattern, replacement, env_contents, flags=re.MULTILINE)
    else:
        # Append new variable
        if not env_contents.endswith("\n"):
            env_contents += "\n"
        env_contents += f"{replacement}\n"

    # Write back to file
    with open(env_file_path, "w") as f:
        f.write(env_contents)

    # Load into environment
    os.environ[var_name] = value


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
