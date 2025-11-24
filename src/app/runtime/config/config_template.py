"""Configuration template substitution utilities."""

import os
import re
from collections.abc import Iterable
from pathlib import Path

import yaml
from loguru import logger
from pydantic_core import ValidationError

from src.app.runtime.config.config_data import ConfigData

_SECRETS_LOADED = False


def _get_project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _candidate_secret_dirs() -> Iterable[Path]:
    custom_dir = os.getenv("SECRETS_KEYS_DIR")
    if custom_dir:
        yield Path(custom_dir)
    project_root = _get_project_root()
    yield project_root / "infra" / "secrets" / "keys"
    yield project_root / "secrets" / "keys"


def _load_secret_files_into_env() -> None:
    global _SECRETS_LOADED
    if _SECRETS_LOADED:
        return

    for directory in _candidate_secret_dirs():
        if not directory.exists() or not directory.is_dir():
            continue

        for file_path in directory.iterdir():
            if not file_path.is_file():
                continue

            env_name = file_path.stem.upper()
            if not env_name or env_name in os.environ:
                continue

            try:
                raw_value = file_path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning(
                    "Unable to read secret file %s: %s",
                    file_path,
                    exc,
                )
                continue

            value = raw_value.strip()
            if value:
                os.environ[env_name] = value

        break

    _SECRETS_LOADED = True


def substitute_env_vars(text: str) -> str:
    """
    Substitute environment variable placeholders in text.

    Supports formats:
    - ${VAR_NAME} - required variable (raises error if missing)
    - ${VAR_NAME:-default} - optional with default value
    - ${VAR_NAME:?error_message} - required with custom error message
    """

    _load_secret_files_into_env()

    def replacer(match):
        var_expr = match.group(1)

        # Handle default values: ${VAR:-default}
        if ":-" in var_expr:
            var_name, default = var_expr.split(":-", 1)
            return os.getenv(var_name, default)

        # Handle error messages: ${VAR:?message}
        elif ":?" in var_expr:
            var_name, error_msg = var_expr.split(":?", 1)
            value = os.getenv(var_name)
            if value is None:
                raise ValueError(f"Required environment variable {var_name}: {error_msg}")
            return value

        # Handle required variables: ${VAR}
        else:
            var_name = var_expr
            value = os.getenv(var_name)
            if value is None:
                raise ValueError(f"Required environment variable {var_name} not set")
            return value

    # Match ${...} patterns
    pattern = r'\$\{([^}]+)\}'
    return re.sub(pattern, replacer, text)


def load_templated_yaml(file_path: Path) -> ConfigData:
    """
    Load a YAML file with environment variable substitution.

    Args:
        file_path: Path to the YAML file

    Returns:
        Parsed YAML with environment variables substituted

    Raises:
        ValueError: If required environment variables are missing
        FileNotFoundError: If the YAML file doesn't exist
    """
    with open(file_path) as f:
        content = f.read()

    # Use correct variables based on environment

    # Get environment mode
    env_mode = os.getenv("APP_ENVIRONMENT", "development")
    logger.info(f"Loading configuration for environment: {env_mode}")

    # Iterate through all environment variables with the prefix matching the env_mode and return (name, value) pairs of all matching variables
    env_variables = [(var, value) for var, value in os.environ.items() if var.startswith(f"{env_mode.upper()}_")]
    logger.info(f"Applying environment-specific overrides: {env_variables}")

    # Now create new environment variables from the matching variables above by removing the prefix
    for var_name, var_value in env_variables:
        new_var_name = var_name[len(f"{env_mode.upper()}_"):]

        os.environ[new_var_name] = var_value
        logger.debug(f"Set environment variable {new_var_name} from {var_name}")

    # Substitute environment variables
    substituted_content = substitute_env_vars(content)

    # Parse YAML
    try:
        loaded = yaml.safe_load(substituted_content)
        if not loaded:
            raise ValueError("Failed to parse YAML")
    except yaml.YAMLError as e:
        raise ValueError(f"Error parsing YAML: {e}") from e

    # Validate and return as ConfigData
    try:
        # Extract the 'config' section from the YAML structure
        config_data = loaded.get('config', {})
        config = ConfigData(**config_data)
    except ValidationError as e:
        raise ValueError(f"Invalid configuration: {e}") from e


    # Remove any OIDC providers that are disabled or use_in_production in non-development environments
    if config.oidc and config.oidc.providers:
        enabled_providers = {}
        for name, provider in config.oidc.providers.items():
            if provider.enabled:
                if provider.dev_only and (env_mode != "development" and env_mode != "test"):
                    logger.info(f"Skipping OIDC provider '{name}' in non-development environment")
                    continue
                enabled_providers[name] = provider
            else:
                logger.info(f"Skipping disabled OIDC provider '{name}'")
        config.oidc.providers = enabled_providers

        if not config.oidc.providers:
            logger.warning("No OIDC providers are enabled after applying configuration filters")

        config.oidc.providers = enabled_providers

    # Clear Redis password for development environment (dev Redis has no auth)
    if env_mode == "development" and config.redis and config.redis.password:
        logger.info("Clearing Redis password for development environment (dev Redis has no authentication)")
        config.redis.password = ""

    return config


def validate_config_env_vars() -> dict[str, str]:
    """
    Validate that all required environment variables are set.

    Returns:
        Dictionary of missing variables and their descriptions
    """
    required_vars = {
        'OIDC_KEYCLOAK_CLIENT_ID': 'Keycloak OAuth client ID',
        'OIDC_KEYCLOAK_CLIENT_SECRET': 'Keycloak OAuth client secret',
    }

    missing = {}
    for var, description in required_vars.items():
        if not os.getenv(var):
            missing[var] = description

    return missing


# Example usage
if __name__ == "__main__":
    try:
        config_path = Path("config.yaml")

        config = load_templated_yaml(config_path)
        print("Configuration loaded successfully:")
        print(f"Redis URL: {config.redis.url}")
        print(f"Database URL: {config.database.url}")
        print(f"Keycloak Client ID: {config.oidc.providers['keycloak'].client_id}")
    except ValueError as e:
        print(f"Configuration error: {e}")
    except FileNotFoundError:
        print("config.yaml not found")
