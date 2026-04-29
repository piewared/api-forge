"""Unit tests for deployment_targets module."""

import tempfile
from pathlib import Path

import pytest

from src.app.runtime.config.deployment_targets import (
    DeploymentTarget,
    ServiceDefaults,
    parse_service_defaults,
    resolve_fly_service_urls,
)


class TestParseServiceDefaults:
    """Verify extraction of service defaults from config.yaml patterns."""

    @pytest.fixture()
    def config_file(self, tmp_path: Path) -> Path:
        """Create a minimal config.yaml with ${VAR:-default} patterns."""
        content = """\
config:
  temporal:
    url: "${TEMPORAL_URL:-temporal:7233}"
  redis:
    url: "${REDIS_URL:-redis://localhost:6379}"
  database:
    url: "${DATABASE_URL:-postgresql+asyncpg://appuser@postgres:5432/appdb}"
"""
        path = tmp_path / "config.yaml"
        path.write_text(content)
        return path

    def test_parses_temporal_defaults(self, config_file: Path):
        defaults = parse_service_defaults(config_file)
        assert defaults.temporal_host == "temporal"
        assert defaults.temporal_port == 7233

    def test_parses_redis_defaults(self, config_file: Path):
        defaults = parse_service_defaults(config_file)
        assert defaults.redis_scheme == "redis"
        assert defaults.redis_host == "localhost"
        assert defaults.redis_port == 6379

    def test_parses_database_defaults(self, config_file: Path):
        defaults = parse_service_defaults(config_file)
        assert defaults.database_host == "postgres"
        assert defaults.database_port == 5432

    def test_parses_real_config(self):
        """Parse the actual project config.yaml."""
        real_config = Path("config.yaml")
        if not real_config.exists():
            pytest.skip("config.yaml not in working directory")
        defaults = parse_service_defaults(real_config)
        assert defaults.temporal_port == 7233
        assert defaults.redis_port == 6379
        assert defaults.database_port == 5432


class TestResolveFlyServiceUrls:
    """Verify Fly.io .internal URL generation."""

    @pytest.fixture()
    def defaults(self) -> ServiceDefaults:
        return ServiceDefaults(
            temporal_host="temporal",
            temporal_port=7233,
            redis_scheme="redis",
            redis_host="localhost",
            redis_port=6379,
            redis_path="/0",
            database_host="postgres",
            database_port=5432,
        )

    def test_temporal_url_format(self, defaults: ServiceDefaults):
        urls = resolve_fly_service_urls(defaults, "my-app")
        assert urls["TEMPORAL_URL"] == "my-app-temporal.internal:7233"

    def test_redis_url_format(self, defaults: ServiceDefaults):
        urls = resolve_fly_service_urls(defaults, "my-app")
        assert urls["REDIS_URL"] == "redis://my-app-redis.internal:6379/0"

    def test_no_production_prefixed_keys(self, defaults: ServiceDefaults):
        urls = resolve_fly_service_urls(defaults, "my-app")
        assert "PRODUCTION_TEMPORAL_URL" not in urls
        assert "PRODUCTION_REDIS_URL" not in urls

    def test_uses_custom_port(self):
        defaults = ServiceDefaults(
            temporal_host="t",
            temporal_port=9999,
            redis_scheme="rediss",
            redis_host="r",
            redis_port=6380,
            redis_path="/1",
            database_host="d",
            database_port=5432,
        )
        urls = resolve_fly_service_urls(defaults, "test")
        assert ":9999" in urls["TEMPORAL_URL"]
        assert "rediss://" in urls["REDIS_URL"]
        assert ":6380" in urls["REDIS_URL"]
        assert "/1" in urls["REDIS_URL"]
