"""Unit tests for config_loader module."""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.app.runtime.config.config_loader import load_config, save_config


class TestConfigLoaderRoundTrip:
    """Test that config files maintain their structure through load/save cycles."""

    def test_preserves_env_var_strings_with_dollar_signs(self):
        """Strings with ${...} patterns should remain quoted after round-trip."""
        test_config = {
            'config': {
                'database': {
                    'url': '${DATABASE_URL:-postgresql://localhost/db}'
                },
                'oidc': {
                    'client_secret': '${OIDC_CLIENT_SECRET}'
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(test_config, f)
            temp_path = Path(f.name)

        try:
            # Load without processing
            loaded = load_config(temp_path, processed=False)

            # Save to a new file
            save_path = temp_path.with_suffix('.saved.yaml')
            from src.app.runtime.config.config_loader import CONFIG_PATH
            original_config_path = CONFIG_PATH
            import src.app.runtime.config.config_loader as config_loader_module
            config_loader_module.CONFIG_PATH = save_path

            try:
                save_config(loaded)

                # Read the saved file and verify quotes are preserved
                with open(save_path) as f:
                    saved_content = f.read()

                # Check that env var patterns are quoted
                assert '"${DATABASE_URL:-postgresql://localhost/db}"' in saved_content
                assert '"${OIDC_CLIENT_SECRET}"' in saved_content

                # Verify it can be loaded again without type errors
                reloaded = yaml.safe_load(saved_content)
                assert reloaded['config']['database']['url'] == '${DATABASE_URL:-postgresql://localhost/db}'
                assert reloaded['config']['oidc']['client_secret'] == '${OIDC_CLIENT_SECRET}'
            finally:
                config_loader_module.CONFIG_PATH = original_config_path
                if save_path.exists():
                    save_path.unlink()
        finally:
            temp_path.unlink()

    def test_preserves_numeric_strings(self):
        """Numeric-looking strings should remain quoted to preserve string type."""
        test_config = {
            'config': {
                'secrets': {
                    'pin': '1234',
                    'token': '999',
                    'id': '42'
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(test_config, f)
            temp_path = Path(f.name)

        try:
            loaded = load_config(temp_path, processed=False)

            save_path = temp_path.with_suffix('.saved.yaml')
            from src.app.runtime.config.config_loader import CONFIG_PATH
            original_config_path = CONFIG_PATH
            import src.app.runtime.config.config_loader as config_loader_module
            config_loader_module.CONFIG_PATH = save_path

            try:
                save_config(loaded)

                with open(save_path) as f:
                    saved_content = f.read()

                # Verify numeric strings are quoted
                assert '"1234"' in saved_content
                assert '"999"' in saved_content
                assert '"42"' in saved_content

                # Verify they remain strings when reloaded
                reloaded = yaml.safe_load(saved_content)
                assert isinstance(reloaded['config']['secrets']['pin'], str)
                assert isinstance(reloaded['config']['secrets']['token'], str)
                assert isinstance(reloaded['config']['secrets']['id'], str)
            finally:
                config_loader_module.CONFIG_PATH = original_config_path
                if save_path.exists():
                    save_path.unlink()
        finally:
            temp_path.unlink()

    def test_normal_strings_not_unnecessarily_quoted(self):
        """Regular strings without special characters should use default representation."""
        test_config = {
            'config': {
                'app': {
                    'name': 'my-app',
                    'description': 'A test application',
                    'environment': 'development'
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(test_config, f)
            temp_path = Path(f.name)

        try:
            loaded = load_config(temp_path, processed=False)

            save_path = temp_path.with_suffix('.saved.yaml')
            from src.app.runtime.config.config_loader import CONFIG_PATH
            original_config_path = CONFIG_PATH
            import src.app.runtime.config.config_loader as config_loader_module
            config_loader_module.CONFIG_PATH = save_path

            try:
                save_config(loaded)

                with open(save_path) as f:
                    saved_content = f.read()

                # Normal strings can be unquoted in YAML
                reloaded = yaml.safe_load(saved_content)
                assert reloaded['config']['app']['name'] == 'my-app'
                assert reloaded['config']['app']['description'] == 'A test application'
                assert reloaded['config']['app']['environment'] == 'development'
            finally:
                config_loader_module.CONFIG_PATH = original_config_path
                if save_path.exists():
                    save_path.unlink()
        finally:
            temp_path.unlink()

    def test_mixed_content_round_trip(self):
        """Test round-trip with mixed content types."""
        test_config = {
            'config': {
                'database': {
                    'url': '${DATABASE_URL}',
                    'port': 5432,  # Real integer
                    'max_connections': 10,
                    'ssl_mode': 'require'
                },
                'secrets': {
                    'api_key': '12345',  # Numeric string
                    'session_secret': 'normal-secret-string'
                },
                'features': {
                    'enabled': True,
                    'rate_limit': 100
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(test_config, f)
            temp_path = Path(f.name)

        try:
            loaded = load_config(temp_path, processed=False)

            save_path = temp_path.with_suffix('.saved.yaml')
            from src.app.runtime.config.config_loader import CONFIG_PATH
            original_config_path = CONFIG_PATH
            import src.app.runtime.config.config_loader as config_loader_module
            config_loader_module.CONFIG_PATH = save_path

            try:
                save_config(loaded)

                with open(save_path) as f:
                    saved_content = f.read()

                reloaded = yaml.safe_load(saved_content)

                # Verify types are preserved
                assert isinstance(reloaded['config']['database']['url'], str)
                assert reloaded['config']['database']['url'] == '${DATABASE_URL}'

                assert isinstance(reloaded['config']['database']['port'], int)
                assert reloaded['config']['database']['port'] == 5432

                assert isinstance(reloaded['config']['secrets']['api_key'], str)
                assert reloaded['config']['secrets']['api_key'] == '12345'

                assert isinstance(reloaded['config']['features']['enabled'], bool)
                assert reloaded['config']['features']['enabled'] is True
            finally:
                config_loader_module.CONFIG_PATH = original_config_path
                if save_path.exists():
                    save_path.unlink()
        finally:
            temp_path.unlink()


class TestConfigLoaderEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_string_values(self):
        """Empty strings should be preserved."""
        test_config = {
            'config': {
                'optional': {
                    'value': ''
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(test_config, f)
            temp_path = Path(f.name)

        try:
            loaded = load_config(temp_path, processed=False)
            assert loaded['config']['optional']['value'] == ''
        finally:
            temp_path.unlink()

    def test_strings_with_colons_and_special_chars(self):
        """Strings with special YAML characters should be handled correctly."""
        test_config = {
            'config': {
                'urls': {
                    'with_colon': 'http://localhost:8000',
                    'with_hash': 'secret#123',
                    'with_at': 'user@example.com'
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(test_config, f)
            temp_path = Path(f.name)

        try:
            loaded = load_config(temp_path, processed=False)

            save_path = temp_path.with_suffix('.saved.yaml')
            from src.app.runtime.config.config_loader import CONFIG_PATH
            original_config_path = CONFIG_PATH
            import src.app.runtime.config.config_loader as config_loader_module
            config_loader_module.CONFIG_PATH = save_path

            try:
                save_config(loaded)

                reloaded = yaml.safe_load(save_path.read_text())
                assert reloaded['config']['urls']['with_colon'] == 'http://localhost:8000'
                assert reloaded['config']['urls']['with_hash'] == 'secret#123'
                assert reloaded['config']['urls']['with_at'] == 'user@example.com'
            finally:
                config_loader_module.CONFIG_PATH = original_config_path
                if save_path.exists():
                    save_path.unlink()
        finally:
            temp_path.unlink()

    def test_zero_and_false_values(self):
        """Zero and false values should be preserved correctly."""
        test_config = {
            'config': {
                'values': {
                    'zero_int': 0,
                    'zero_string': '0',
                    'false_bool': False,
                    'false_string': 'false'
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(test_config, f)
            temp_path = Path(f.name)

        try:
            loaded = load_config(temp_path, processed=False)

            save_path = temp_path.with_suffix('.saved.yaml')
            from src.app.runtime.config.config_loader import CONFIG_PATH
            original_config_path = CONFIG_PATH
            import src.app.runtime.config.config_loader as config_loader_module
            config_loader_module.CONFIG_PATH = save_path

            try:
                save_config(loaded)

                reloaded = yaml.safe_load(save_path.read_text())

                # Verify types
                assert reloaded['config']['values']['zero_int'] == 0
                assert isinstance(reloaded['config']['values']['zero_int'], int)

                assert reloaded['config']['values']['zero_string'] == '0'
                assert isinstance(reloaded['config']['values']['zero_string'], str)

                assert reloaded['config']['values']['false_bool'] is False
                assert isinstance(reloaded['config']['values']['false_bool'], bool)

                assert reloaded['config']['values']['false_string'] == 'false'
                assert isinstance(reloaded['config']['values']['false_string'], str)
            finally:
                config_loader_module.CONFIG_PATH = original_config_path
                if save_path.exists():
                    save_path.unlink()
        finally:
            temp_path.unlink()
