"""Unit tests for env_resolver module."""

from src.cli.deployment.env_resolver import resolve_env_for_target


class TestResolveEnvForTarget:
    """Verify target-aware environment variable resolution."""

    def test_promotes_production_vars(self):
        env = {
            "PRODUCTION_DATABASE_URL": "postgres://prod:5432/db",
            "APP_ENVIRONMENT": "development",
        }
        result = resolve_env_for_target(env, "production")
        assert result["DATABASE_URL"] == "postgres://prod:5432/db"
        assert "PRODUCTION_DATABASE_URL" not in result

    def test_strips_development_vars(self):
        env = {
            "DEVELOPMENT_DATABASE_URL": "postgres://dev:5433/db",
            "PRODUCTION_DATABASE_URL": "postgres://prod:5432/db",
            "APP_ENVIRONMENT": "development",
        }
        result = resolve_env_for_target(env, "production")
        assert "DEVELOPMENT_DATABASE_URL" not in result

    def test_strips_test_vars(self):
        env = {"TEST_DATABASE_URL": "sqlite://memory"}
        result = resolve_env_for_target(env, "production")
        assert "TEST_DATABASE_URL" not in result

    def test_strips_placeholder_values(self):
        env = {
            "SESSION_SECRET": "your-secret-CHANGE_ME!",
            "REAL_KEY": "actual-value",
        }
        result = resolve_env_for_target(env, "production")
        assert "SESSION_SECRET" not in result
        assert result["REAL_KEY"] == "actual-value"

    def test_strips_your_prefix_placeholders(self):
        env = {"API_KEY": "your-api-key"}
        result = resolve_env_for_target(env, "production")
        assert "API_KEY" not in result

    def test_strips_empty_values(self):
        env = {"EMPTY": "", "NOTEMPTY": "value"}
        result = resolve_env_for_target(env, "production")
        assert "EMPTY" not in result
        assert result["NOTEMPTY"] == "value"

    def test_preserves_non_prefixed_vars(self):
        env = {
            "APP_ENVIRONMENT": "production",
            "PG_SUPERUSER": "postgres",
            "FLY_APP_NAME": "my-app",
        }
        result = resolve_env_for_target(env, "production")
        assert result["APP_ENVIRONMENT"] == "production"
        assert result["PG_SUPERUSER"] == "postgres"
        assert result["FLY_APP_NAME"] == "my-app"

    def test_full_pipeline_matches_expected(self):
        """Simulate a realistic .env and verify the output is clean."""
        env = {
            "APP_ENVIRONMENT": "development",
            "PRODUCTION_DATABASE_URL": "postgresql://postgres:5432/postgres",
            "DEVELOPMENT_DATABASE_URL": "postgresql://appuser:devpass@localhost:5433/appdb",
            "PRODUCTION_REDIS_URL": "redis://redis:6379/0",
            "DEVELOPMENT_REDIS_URL": "redis://localhost:6380/0",
            "PG_SUPERUSER": "postgres",
            "SESSION_SIGNING_SECRET": "your-session-signing-secret-CHANGE_ME!",
            "FLY_APP_NAME": "my-app",
        }
        result = resolve_env_for_target(env, "production")

        # Promoted plain keys present
        assert result["DATABASE_URL"] == "postgresql://postgres:5432/postgres"
        assert result["REDIS_URL"] == "redis://redis:6379/0"

        # No prefixed keys
        assert not any(k.startswith("PRODUCTION_") for k in result)
        assert not any(k.startswith("DEVELOPMENT_") for k in result)

        # No placeholders
        assert "SESSION_SIGNING_SECRET" not in result

        # Non-prefixed vars preserved
        assert result["PG_SUPERUSER"] == "postgres"
        assert result["FLY_APP_NAME"] == "my-app"
