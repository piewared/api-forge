"""Unit tests for DockerComposeParser."""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.infra.docker_compose import DockerComposeParser


@pytest.fixture
def sample_compose_dict():
    """Sample docker-compose configuration as a dictionary."""
    return {
        "version": "3.8",
        "services": {
            "redis": {
                "build": {
                    "context": "infra/docker/prod/redis",
                    "dockerfile": "Dockerfile",
                },
                "environment": {
                    "REDIS_PASSWORD_FILE": "/run/secrets/redis_password",
                    "LOG_LEVEL": "${LOG_LEVEL:-INFO}",
                    "x-template-var": "skip-this",
                },
                "secrets": ["redis_password", "postgres_ca"],
                "volumes": [
                    "redis_data:/data",
                    "redis_backups:/backups",
                    "./local-bind:/host",
                    "/absolute/bind:/container",
                ],
                "ports": ["6379:6379"],
            },
            "temporal-web": {
                "image": "temporalio/ui:2.34.0",
                "environment": [
                    "TEMPORAL_ADDRESS=temporal:7233",
                    "TZ=UTC",
                ],
                "ports": ["8080"],
            },
            "app": {
                "build": {
                    "context": ".",
                    "dockerfile": "Dockerfile",
                },
                "environment": {
                    "APP_ENV": "production",
                    "SECRET_KEY": "${SECRET_KEY}",  # No default - should be skipped
                    "DATABASE_URL": "${DATABASE_URL:-postgresql://localhost}",
                },
                "secrets": [
                    {"source": "app_secret", "target": "/run/secrets/app_secret"},
                    "postgres_app_user_pw",
                    "server.crt",
                    "server_tls_key",
                ],
                "volumes": ["app_data:/data"],
            },
        },
    }


@pytest.fixture
def temp_compose_file(sample_compose_dict):
    """Create a temporary docker-compose.yml file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump(sample_compose_dict, f)
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    temp_path.unlink()


@pytest.fixture
def parser(temp_compose_file):
    """Create a DockerComposeParser instance with temporary file."""
    return DockerComposeParser(temp_compose_file)


class TestDockerComposeParserInit:
    """Tests for DockerComposeParser initialization."""

    def test_init_with_existing_file(self, temp_compose_file):
        """Test initialization with an existing file."""
        parser = DockerComposeParser(temp_compose_file)
        assert parser.compose_file_path == temp_compose_file
        assert parser._compose_data is None  # Lazy loading

    def test_init_with_nonexistent_file(self):
        """Test initialization with a nonexistent file."""
        nonexistent = Path("/tmp/nonexistent-compose.yml")
        parser = DockerComposeParser(nonexistent)
        assert parser.compose_file_path == nonexistent

    def test_load_compose_file_caching(self, parser):
        """Test that compose file data is cached after first load."""
        # First load
        data1 = parser._load_compose_file()
        assert data1 is not None
        assert parser._compose_data is not None

        # Second load should return cached data
        data2 = parser._load_compose_file()
        assert data2 is data1  # Same object reference


class TestGetServiceConfig:
    """Tests for get_service_config method."""

    def test_get_existing_service(self, parser):
        """Test getting config for an existing service."""
        config = parser.get_service_config("redis")

        assert config is not None
        assert "environment" in config
        assert "secrets" in config
        assert "volumes" in config
        assert "ports" in config
        assert config["build"] is not None

    def test_get_nonexistent_service(self, parser):
        """Test getting config for a service that doesn't exist."""
        config = parser.get_service_config("nonexistent")
        assert config == {}

    def test_parse_dict_environment(self, parser):
        """Test parsing environment variables in dict format."""
        config = parser.get_service_config("redis")
        env = config["environment"]

        assert isinstance(env, dict)
        assert env["REDIS_PASSWORD_FILE"] == "/run/secrets/redis_password"
        assert env["LOG_LEVEL"] == "${LOG_LEVEL:-INFO}"

    def test_parse_list_environment(self, parser):
        """Test parsing environment variables in list format."""
        config = parser.get_service_config("temporal-web")
        env = config["environment"]

        assert isinstance(env, dict)
        assert env["TEMPORAL_ADDRESS"] == "temporal:7233"
        assert env["TZ"] == "UTC"

    def test_parse_string_secrets(self, parser):
        """Test parsing secrets in string format."""
        config = parser.get_service_config("redis")
        secrets = config["secrets"]

        assert isinstance(secrets, list)
        assert "redis_password" in secrets
        assert "postgres_ca" in secrets

    def test_parse_dict_secrets(self, parser):
        """Test parsing secrets in dict format with source/target."""
        config = parser.get_service_config("app")
        secrets = config["secrets"]

        assert isinstance(secrets, list)
        assert "app_secret" in secrets
        assert "postgres_app_user_pw" in secrets

    def test_parse_volumes(self, parser):
        """Test parsing volumes."""
        config = parser.get_service_config("redis")
        volumes = config["volumes"]

        assert isinstance(volumes, list)
        assert "redis_data:/data" in volumes
        assert "./local-bind:/host" in volumes

    def test_parse_ports(self, parser):
        """Test parsing ports."""
        config = parser.get_service_config("redis")
        ports = config["ports"]

        assert isinstance(ports, list)
        assert "6379:6379" in ports

    def test_image_field(self, parser):
        """Test that image field is extracted."""
        config = parser.get_service_config("temporal-web")
        assert config["image"] == "temporalio/ui:2.34.0"

    def test_build_field(self, parser):
        """Test that build field is extracted."""
        config = parser.get_service_config("redis")
        assert config["build"] is not None
        assert config["build"]["context"] == "infra/docker/prod/redis"


class TestGetKeySecrets:
    """Tests for get_key_secrets method."""

    def test_filters_certificate_secrets(self, parser):
        """Test that certificate-related secrets are filtered out."""
        secrets = parser.get_key_secrets("app")

        # Should include regular secrets
        assert "postgres_app_user_pw" in secrets
        assert "app_secret" in secrets

        # Should exclude certificate secrets
        assert "server.crt" not in secrets
        assert "server_tls_key" not in secrets

    def test_all_key_secrets_included(self, parser):
        """Test that all non-certificate secrets are included."""
        secrets = parser.get_key_secrets("redis")

        assert "redis_password" in secrets
        # postgres_ca might be filtered if it matches certificate patterns
        # but regular secrets should be there

    def test_nonexistent_service(self, parser):
        """Test get_key_secrets for nonexistent service."""
        secrets = parser.get_key_secrets("nonexistent")
        assert secrets == []


class TestGetResolvedEnvironment:
    """Tests for get_resolved_environment method."""

    def test_resolves_default_values(self, parser):
        """Test that ${VAR:-default} syntax is resolved to default."""
        env = parser.get_resolved_environment("redis")

        # Should resolve to default value
        assert env["LOG_LEVEL"] == "INFO"

    def test_skips_vars_without_defaults(self, parser):
        """Test that ${VAR} without defaults are skipped."""
        env = parser.get_resolved_environment("app")

        # Should be skipped (no default)
        assert "SECRET_KEY" not in env

        # Should be resolved (has default)
        assert env["DATABASE_URL"] == "postgresql://localhost"

    def test_keeps_regular_vars(self, parser):
        """Test that regular variables are kept."""
        env = parser.get_resolved_environment("redis")

        assert env["REDIS_PASSWORD_FILE"] == "/run/secrets/redis_password"

    def test_filters_x_prefix_vars(self, parser):
        """Test that x-* template variables are filtered."""
        env = parser.get_resolved_environment("redis")

        assert "x-template-var" not in env

    def test_list_format_environment(self, parser):
        """Test resolving environment from list format."""
        env = parser.get_resolved_environment("temporal-web")

        assert env["TEMPORAL_ADDRESS"] == "temporal:7233"
        assert env["TZ"] == "UTC"


class TestGetNamedVolumes:
    """Tests for get_named_volumes method."""

    def test_extracts_named_volumes(self, parser):
        """Test that named volumes are extracted correctly."""
        volumes = parser.get_named_volumes("redis")

        assert ("redis_data", "/data") in volumes
        assert ("redis_backups", "/backups") in volumes

    def test_filters_bind_mounts(self, parser):
        """Test that bind mounts are filtered out."""
        volumes = parser.get_named_volumes("redis")

        # Should not include bind mounts
        volume_sources = [v[0] for v in volumes]
        assert "./local-bind" not in volume_sources
        assert "/absolute/bind" not in volume_sources

    def test_nonexistent_service(self, parser):
        """Test get_named_volumes for nonexistent service."""
        volumes = parser.get_named_volumes("nonexistent")
        assert volumes == []


class TestGetDockerfilePath:
    """Tests for get_dockerfile_path method."""

    def test_returns_path_for_build_service(self, parser):
        """Test that Dockerfile path is returned for services with build config."""
        project_root = Path("/project")
        dockerfile_path = parser.get_dockerfile_path("redis", project_root)

        assert dockerfile_path is not None
        assert (
            dockerfile_path == project_root / "infra/docker/prod/redis" / "Dockerfile"
        )

    def test_returns_none_for_image_service(self, parser):
        """Test that None is returned for services using pre-built images."""
        project_root = Path("/project")
        dockerfile_path = parser.get_dockerfile_path("temporal-web", project_root)

        assert dockerfile_path is None

    def test_default_dockerfile_name(self, parser):
        """Test that 'Dockerfile' is used as default."""
        project_root = Path("/project")
        dockerfile_path = parser.get_dockerfile_path("app", project_root)

        assert dockerfile_path is not None
        assert dockerfile_path.name == "Dockerfile"

    def test_nonexistent_service(self, parser):
        """Test get_dockerfile_path for nonexistent service."""
        project_root = Path("/project")
        dockerfile_path = parser.get_dockerfile_path("nonexistent", project_root)

        assert dockerfile_path is None


class TestGetImage:
    """Tests for get_image method."""

    def test_returns_image_for_image_service(self, parser):
        """Test that image name is returned for services using images."""
        image = parser.get_image("temporal-web")

        assert image == "temporalio/ui:2.34.0"

    def test_returns_none_for_build_service(self, parser):
        """Test that None is returned for services with build config."""
        image = parser.get_image("redis")

        assert image is None

    def test_nonexistent_service(self, parser):
        """Test get_image for nonexistent service."""
        image = parser.get_image("nonexistent")

        assert image is None


class TestListServices:
    """Tests for list_services method."""

    def test_lists_all_services(self, parser):
        """Test that all services are listed."""
        services = parser.list_services()

        assert isinstance(services, list)
        assert "redis" in services
        assert "temporal-web" in services
        assert "app" in services

    def test_returns_empty_for_nonexistent_file(self):
        """Test that empty list is returned for nonexistent file."""
        parser = DockerComposeParser(Path("/tmp/nonexistent.yml"))
        services = parser.list_services()

        assert services == []


class TestServiceExists:
    """Tests for service_exists method."""

    def test_existing_service(self, parser):
        """Test that existing services return True."""
        assert parser.service_exists("redis") is True
        assert parser.service_exists("temporal-web") is True
        assert parser.service_exists("app") is True

    def test_nonexistent_service(self, parser):
        """Test that nonexistent services return False."""
        assert parser.service_exists("nonexistent") is False
        assert parser.service_exists("") is False


class TestLoadServiceConfig:
    """Tests for load_service_config convenience function."""

    def test_load_with_explicit_path(self, temp_compose_file):
        """Test loading with an explicit compose file path."""
        from src.infra.docker_compose import load_service_config

        config = load_service_config("redis", temp_compose_file)

        assert config is not None
        assert "environment" in config
        assert config["build"] is not None

    def test_load_nonexistent_service(self, temp_compose_file):
        """Test loading a nonexistent service."""
        from src.infra.docker_compose import load_service_config

        config = load_service_config("nonexistent", temp_compose_file)

        assert config == {}


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_compose_file(self):
        """Test handling of empty compose file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("")
            temp_path = Path(f.name)

        try:
            parser = DockerComposeParser(temp_path)
            services = parser.list_services()
            assert services == []
        finally:
            temp_path.unlink()

    def test_compose_file_without_services(self):
        """Test handling of compose file without services section."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump({"version": "3.8"}, f)
            temp_path = Path(f.name)

        try:
            parser = DockerComposeParser(temp_path)
            services = parser.list_services()
            assert services == []
        finally:
            temp_path.unlink()

    def test_service_with_minimal_config(self):
        """Test handling of service with minimal configuration."""
        minimal_compose = {
            "services": {
                "minimal": {
                    "image": "nginx:latest",
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(minimal_compose, f)
            temp_path = Path(f.name)

        try:
            parser = DockerComposeParser(temp_path)
            config = parser.get_service_config("minimal")

            assert config["image"] == "nginx:latest"
            assert config["environment"] == {}
            assert config["secrets"] == []
            assert config["volumes"] == []
        finally:
            temp_path.unlink()
