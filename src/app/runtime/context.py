from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace

from pydantic import BaseModel

from src.app.runtime.config.config_data import ConfigData
from src.app.runtime.config.config_loader import load_config


@dataclass
class AppContext:
    """Application context containing configuration and other app-wide state."""

    config: ConfigData


# Global configuration instance
_default_config = None
_default_context = None


def _get_default_config():
    """Lazily load the default configuration."""
    global _default_config, _default_context
    if _default_config is None:
        # Load environment variables before config parsing
        # Load order: .env.dev first (if development), then .env
        # This gives precedence: shell vars > .env.dev > .env
        import os

        from dotenv import load_dotenv

        if os.environ.get("APP_ENVIRONMENT") == "development":
            load_dotenv(".env.dev")
        load_dotenv()  # Base .env loaded last (lowest priority)

        _default_config = load_config()
        _default_context = AppContext(config=_default_config)
    return _default_config


def _get_default_context() -> AppContext:
    """Lazily get the default context."""
    global _default_context
    if _default_context is None:
        _get_default_config()  # This will set both _default_config and _default_context
    return _default_context  # type: ignore


# Context variable for application context
_app_context: ContextVar[AppContext] = ContextVar("app_context")


def get_context() -> AppContext:
    """Get the current application context.

    Returns:
        AppContext: The current application context containing configuration.
    """
    try:
        return _app_context.get()
    except LookupError:
        # No context set, return default
        return _get_default_context()


def set_context(context: AppContext) -> Token[AppContext]:
    """Set the current application context.

    Args:
        context: AppContext instance to set as current.
    """
    return _app_context.set(context)


def _recursive_model_dump_exclude_unset(model: BaseModel) -> dict:
    """Recursively dump a Pydantic model with exclude_unset=True for all nested models.

    This function works from the deepest levels up, so that if any nested field
    is explicitly set, the parent field containing that nested model is also included.

    Args:
        model: The Pydantic model to dump

    Returns:
        dict: Dictionary containing only explicitly set fields at all levels
    """
    result = {}

    # Get explicitly set fields at this level
    explicitly_set_fields = model.model_fields_set

    # Check all fields in the model
    for field_name, _field_info in model.__class__.model_fields.items():
        field_value = getattr(model, field_name)

        if isinstance(field_value, BaseModel):
            # Recursively check nested Pydantic models
            nested_result = _recursive_model_dump_exclude_unset(field_value)
            if nested_result:
                # If nested model has explicitly set fields, include only those fields
                result[field_name] = nested_result
            elif field_name in explicitly_set_fields:
                # If this nested model field was explicitly set at this level, include it
                result[field_name] = field_value.model_dump()
        elif isinstance(field_value, dict):
            # Handle dict fields that might contain Pydantic models
            nested_dict = {}
            has_nested_changes = False
            for key, value in field_value.items():
                if isinstance(value, BaseModel):
                    nested_result = _recursive_model_dump_exclude_unset(value)
                    if nested_result:
                        nested_dict[key] = value.model_dump()
                        has_nested_changes = True
                    else:
                        nested_dict[key] = value.model_dump()
                else:
                    nested_dict[key] = value

            if has_nested_changes or field_name in explicitly_set_fields:
                result[field_name] = nested_dict
        elif field_name in explicitly_set_fields:
            # Regular field that was explicitly set
            result[field_name] = field_value

    return result


def _recursive_dict_merge(base_dict: dict, override_dict: dict) -> dict:
    """Recursively merge two dictionaries from deepest levels up.

    Args:
        base_dict: The base dictionary to merge into
        override_dict: The override dictionary to merge from

    Returns:
        dict: The merged dictionary
    """
    result = base_dict.copy()

    for key, value in override_dict.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recursively merge nested dictionaries
            result[key] = _recursive_dict_merge(result[key], value)
        else:
            # Override or new key
            result[key] = value

    return result


def _merge_configs(base_config: ConfigData, override_config: ConfigData) -> ConfigData:
    """Recursively merge two ConfigData instances.

    This function merges the override_config into the base_config, with
    values from override_config taking precedence. Nested configurations
    are merged recursively.

    Args:
        base_config: The base ConfigData instance.
        override_config: The override ConfigData instance.
    Returns:
        ConfigData: The merged ConfigData instance.
    """
    base_dict = base_config.model_dump()
    override_dict = _recursive_model_dump_exclude_unset(override_config)
    merged_dict = _recursive_dict_merge(base_dict, override_dict)
    return ConfigData.model_validate(merged_dict)


@contextmanager
def with_context(config_override: ConfigData | None = None):
    """Context manager for temporarily overriding the application context.

    This function merges the override configuration with the current context,
    allowing for partial overrides that inherit non-overridden values from
    the parent context.

    Args:
        config_override: Optional ApplicationConfig instance.
                        If ApplicationConfig, nested fields are properly merged with inheritance.

    Example:
        # Using dict overrides (recommended for partial overrides)
        with with_context({'log_level': 'DEBUG', 'environment': 'prod'}):
            config = get_config()
            assert config.log_level == 'DEBUG'     # Overridden
            assert config.environment == 'prod'    # Overridden

        # Using keyword arguments (recommended for single overrides)
        with with_context(log_level='INFO'):
            config = get_config()
            assert config.log_level == 'INFO'      # Overridden

        # Using ApplicationConfig (properly merges nested configurations)
        override_config = ApplicationConfig()
        override_config.jwt.uid_claim = 'custom_uid'  # Only this field changes
        with with_context(override_config):
            config = get_config()
            # config.jwt.uid_claim is 'custom_uid', other jwt fields inherited
    """
    if config_override is None:
        # No overrides, just yield current context
        yield
        return

    current_config = get_context().config

    if isinstance(config_override, ConfigData):
        # Get only explicitly set fields recursively using our custom function
        merged_config = _merge_configs(current_config, config_override)
    else:
        raise ValueError(
            f"config_override must be ConfigData, or None, got {type(config_override)}"
        )

    token = set_context(replace(get_context(), config=merged_config))
    try:
        yield
    finally:
        _app_context.reset(token)


def set_config(config: ConfigData) -> None:
    """Set the current application configuration.
    This replaces the entire current configuration with the provided one.
    Args:
        config: ConfigData instance to set as current.
    """
    set_context(replace(get_context(), config=config))


def get_config() -> ConfigData:
    """Convenience function to get the current configuration.

    Returns:
        ConfigData: The current configuration from the app context.
    """
    return get_context().config
