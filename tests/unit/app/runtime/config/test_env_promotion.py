"""Unit tests for env_promotion module."""

import pytest

from src.app.runtime.config.env_promotion import promote_env_vars


class TestPromoteEnvVars:
    """Verify single-canonical promotion of prefixed env vars."""

    def test_promotes_production_prefix(self):
        env = {"PRODUCTION_DATABASE_URL": "postgres://prod", "OTHER": "keep"}
        result = promote_env_vars(env, "production")
        assert result["DATABASE_URL"] == "postgres://prod"
        assert result["OTHER"] == "keep"

    def test_promotes_development_prefix(self):
        env = {"DEVELOPMENT_REDIS_URL": "redis://dev:6380/0"}
        result = promote_env_vars(env, "development")
        assert result["REDIS_URL"] == "redis://dev:6380/0"

    def test_promotes_test_prefix(self):
        env = {"TEST_DATABASE_URL": "sqlite://memory"}
        result = promote_env_vars(env, "test")
        assert result["DATABASE_URL"] == "sqlite://memory"

    def test_promoted_key_wins_over_existing(self):
        env = {
            "DATABASE_URL": "old-value",
            "PRODUCTION_DATABASE_URL": "new-value",
        }
        result = promote_env_vars(env, "production")
        assert result["DATABASE_URL"] == "new-value"

    def test_preserves_original_prefixed_keys(self):
        env = {"PRODUCTION_DATABASE_URL": "postgres://prod"}
        result = promote_env_vars(env, "production")
        assert "PRODUCTION_DATABASE_URL" in result
        assert result["PRODUCTION_DATABASE_URL"] == "postgres://prod"

    def test_does_not_mutate_input(self):
        env = {"PRODUCTION_DATABASE_URL": "postgres://prod"}
        original = dict(env)
        promote_env_vars(env, "production")
        assert env == original

    def test_empty_input(self):
        assert promote_env_vars({}, "production") == {}

    def test_no_matching_prefix(self):
        env = {"DATABASE_URL": "keep", "DEVELOPMENT_X": "skip"}
        result = promote_env_vars(env, "production")
        assert result == env  # No PRODUCTION_* keys, nothing promoted

    def test_case_sensitivity_of_mode(self):
        env = {"PRODUCTION_KEY": "val"}
        result = promote_env_vars(env, "Production")
        assert result["KEY"] == "val"
