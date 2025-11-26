import os
from unittest.mock import patch

import pytest

from src.app.runtime.config.config_data import ConfigData as ApplicationConfig
from src.app.runtime.context import get_config, with_context


class TestConfigurationManagement:
    """Test application configuration and context management."""

    def test_default_config_available(self):
        """Test that default configuration is available."""
        config = get_config()
        assert isinstance(config, ApplicationConfig)
        assert config.app.environment == "development"

    def test_config_context_override(self):
        """Test configuration override with context manager."""
        original_config = get_config()
        original_env = original_config.app.environment

        # Create test config
        test_config = ApplicationConfig()
        test_config.app.environment = "test"

        with with_context(config_override=test_config):
            override_config = get_config()
            assert override_config.app.environment == "test"
            assert override_config is not original_config

        # Should revert after context
        after_config = get_config()
        assert after_config.app.environment == original_env

    def test_nested_config_overrides(self):
        """Test nested configuration overrides."""
        test_config1 = ApplicationConfig()
        test_config1.app.environment = "test"

        test_config2 = ApplicationConfig()
        test_config2.app.environment = "production"

        with with_context(config_override=test_config1):
            assert get_config().app.environment == "test"

            with with_context(config_override=test_config2):
                assert get_config().app.environment == "production"

            # Should revert to first override
            assert get_config().app.environment == "test"
