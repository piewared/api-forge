"""Docker Compose configuration parser.

This module provides utilities for parsing docker-compose.yml files
to extract service configurations. It serves as the single source of
truth for service environment variables, secrets, volumes, and other
deployment configurations.
"""

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


class DockerComposeParser:
    """Parser for docker-compose.yml files."""

    def __init__(self, compose_file_path: Path):
        """Initialize the parser with a docker-compose file.

        Args:
            compose_file_path: Path to the docker-compose.yml file
        """
        self.compose_file_path = compose_file_path
        self._compose_data: dict[str, Any] | None = None

    def _load_compose_file(self) -> dict[str, Any]:
        """Load and cache the docker-compose file data.

        Returns:
            Dict with the parsed docker-compose data
        """
        if not self._compose_data:
            if not self.compose_file_path.exists():
                self._compose_data = {}
            else:
                with open(self.compose_file_path) as f:
                    self._compose_data = yaml.safe_load(f) or {}
        return self._compose_data

    def get_service_config(self, service_name: str) -> dict[str, Any]:
        """Get configuration for a specific service.

        Args:
            service_name: Name of the service in docker-compose file

        Returns:
            Dict with service configuration containing:
                - environment: Dict of environment variables
                - secrets: List of secret names
                - volumes: List of volume mount specifications
                - ports: List of port mappings
                - image: Docker image name (if specified)
                - build: Build configuration (if specified)
        """
        compose_data = self._load_compose_file()
        services = compose_data.get("services", {})
        service_config = services.get(service_name, {})

        if not service_config:
            return {}

        # Extract relevant configuration
        config = {
            "environment": {},
            "secrets": [],
            "volumes": [],
            "ports": [],
            "image": service_config.get("image"),
            "build": service_config.get("build"),
            "command": service_config.get("command"),
        }

        # Parse environment variables
        env = service_config.get("environment", {})
        config["environment"] = self._parse_environment(env)

        # Parse secrets
        secrets = service_config.get("secrets", [])
        config["secrets"] = self._parse_secrets(secrets)

        # Parse volumes (for mount points)
        volumes = service_config.get("volumes", [])
        config["volumes"] = self._parse_volumes(volumes)

        # Parse ports
        ports = service_config.get("ports", [])
        config["ports"] = self._parse_ports(ports)

        return config

    def _parse_environment(self, env: dict[str, Any] | list[str]) -> dict[str, str]:
        """Parse environment variables from docker-compose format.

        Handles both dict and list formats:
        - Dict: {KEY: value, KEY2: value2}
        - List: ["KEY=value", "KEY2=value2"]

        Args:
            env: Environment configuration from docker-compose

        Returns:
            Dict of environment variables
        """
        if isinstance(env, dict):
            return {k: str(v) for k, v in env.items()}
        elif isinstance(env, list):
            # Parse list format: ["KEY=value", "KEY2=value2"]
            result = {}
            for item in env:
                if isinstance(item, str) and "=" in item:
                    key, value = item.split("=", 1)
                    result[key] = value
            return result
        return {}

    def _parse_secrets(self, secrets: list[str | dict[str, Any]]) -> list[str]:
        """Parse secrets from docker-compose format.

        Handles both string and dict formats:
        - String: secret_name
        - Dict: {source: secret_name, target: /path/to/secret}

        Args:
            secrets: Secrets configuration from docker-compose

        Returns:
            List of secret names
        """
        if not isinstance(secrets, list):
            return []

        result = []
        for secret in secrets:
            if isinstance(secret, str):
                result.append(secret)
            elif isinstance(secret, dict):
                # Handle format: {source: name, target: path}
                source = secret.get("source", "")
                if source:
                    result.append(source)
        return result

    def _parse_volumes(self, volumes: list[str]) -> list[str]:
        """Parse volumes from docker-compose format.

        Args:
            volumes: Volumes configuration from docker-compose

        Returns:
            List of volume mount specifications
        """
        if not isinstance(volumes, list):
            return []
        return [v for v in volumes if isinstance(v, str)]

    def _parse_ports(self, ports: list[str | int]) -> list[str]:
        """Parse ports from docker-compose format.

        Args:
            ports: Ports configuration from docker-compose

        Returns:
            List of port mappings
        """
        if not isinstance(ports, list):
            return []
        return [str(p) for p in ports]

    def list_services(self) -> list[str]:
        """List all services defined in the docker-compose file.

        Returns:
            List of service names
        """
        compose_data = self._load_compose_file()
        services = compose_data.get("services", {})
        return list(services.keys())

    def service_exists(self, service_name: str) -> bool:
        """Check if a service exists in the docker-compose file.

        Args:
            service_name: Name of the service to check

        Returns:
            True if service exists, False otherwise
        """
        return service_name in self.list_services()

    def get_key_secrets(self, service_name: str) -> list[str]:
        """Get non-certificate secrets for a service.

        Filters out TLS/certificate secrets, returning only key/password secrets.

        Args:
            service_name: Name of the service

        Returns:
            List of secret names (excluding certificates)
        """
        config = self.get_service_config(service_name)
        secrets = config.get("secrets", [])

        # Filter out certificate-related secrets
        cert_indicators = ["_tls_", "_ca", "server.crt", "server.key", "ca-bundle"]
        return [s for s in secrets if not any(ind in s for ind in cert_indicators)]

    def get_resolved_environment(self, service_name: str) -> dict[str, str]:
        """Get environment variables with docker-compose variable syntax resolved.

        Resolves ${VAR:-default} syntax to default values for deployment.
        Skips variables without defaults (assumed to come from secrets).

        Args:
            service_name: Name of the service

        Returns:
            Dict of resolved environment variables
        """
        config = self.get_service_config(service_name)
        env_vars = config.get("environment", {})
        resolved = {}

        for key, value in env_vars.items():
            # Skip x-* template variables
            if key.startswith("x-"):
                continue

            if not isinstance(value, str):
                resolved[key] = str(value)
                continue

            # Resolve ${VAR:-default} or ${VAR} syntax
            if value.startswith("${") and "}" in value:
                # Extract default value if present
                if ":-" in value:
                    default_value = value.split(":-", 1)[1].rstrip("}")
                    resolved[key] = default_value
                # Skip variables without defaults (will come from secrets)
            else:
                resolved[key] = value

        return resolved

    def get_named_volumes(self, service_name: str) -> list[tuple[str, str]]:
        """Get named volume mounts (excluding bind mounts).

        Args:
            service_name: Name of the service

        Returns:
            List of (source, destination) tuples for named volumes
        """
        config = self.get_service_config(service_name)
        volumes = config.get("volumes", [])
        named_volumes = []

        for volume in volumes:
            if not isinstance(volume, str) or ":" not in volume:
                continue

            # Skip bind mounts (start with . or /)
            if volume.startswith(".") or volume.startswith("/"):
                continue

            parts = volume.split(":")
            if len(parts) >= 2:
                source = parts[0]
                destination = parts[1]

                # Only include named volumes, not bind mounts
                if not source.startswith("/") and not source.startswith("."):
                    named_volumes.append((source, destination))

        return named_volumes

    def get_build_context(self, service_name: str, project_root: Path) -> Path | None:
        """Get the Docker build context directory for a service.

        Args:
            service_name: Name of the service
            project_root: Path to the project root directory

        Returns:
            Absolute path to the build context directory, or None if service
            uses a pre-built image.
        """
        config = self.get_service_config(service_name)
        if config.get("image") and not config.get("build"):
            return None
        build_config = config.get("build")
        if isinstance(build_config, dict):
            context = build_config.get("context", ".")
            return (project_root / context).resolve()
        return None

    def get_dockerfile_path(self, service_name: str, project_root: Path) -> Path | None:
        """Get the Dockerfile path for a service.

        Args:
            service_name: Name of the service
            project_root: Path to the project root directory

        Returns:
            Path to Dockerfile, or None if service uses a pre-built image
        """
        config = self.get_service_config(service_name)

        # Check if using pre-built image
        if config.get("image") and not config.get("build"):
            return None

        # Parse build config
        build_config = config.get("build")
        if isinstance(build_config, dict):
            context = build_config.get("context", ".")
            dockerfile = build_config.get("dockerfile", "Dockerfile")
            return project_root / context / dockerfile

        return None

    def get_image(self, service_name: str) -> str | None:
        """Get the Docker image for a service.

        Args:
            service_name: Name of the service

        Returns:
            Image name, or None if service uses a Dockerfile
        """
        config = self.get_service_config(service_name)
        return config.get("image")

    def get_command(self, service_name: str) -> str | None:
        """Get the command override for a service.

        Returns the ``command`` field from docker-compose as a shell string,
        suitable for use in a Fly.io ``[processes]`` section.  Returns None
        when the service has no command override (i.e. uses the image CMD).

        Args:
            service_name: Name of the service

        Returns:
            Shell command string, or None if no override is defined
        """
        config = self.get_service_config(service_name)
        cmd = config.get("command")
        if cmd is None:
            return None
        if isinstance(cmd, list):
            import shlex

            return shlex.join(cmd)
        return str(cmd)


def load_service_config(
    service_name: str, compose_file_path: Path | None = None
) -> dict[str, Any]:
    """Convenience function to load service config from docker-compose file.

    Args:
        service_name: Name of the service in docker-compose file
        compose_file_path: Path to docker-compose file (defaults to docker-compose.prod.yml in project root)

    Returns:
        Dict with service configuration (environment, secrets, volumes, etc.)
    """
    if compose_file_path is None:
        from src.utils.paths import get_project_root

        compose_file_path = get_project_root() / "docker-compose.prod.yml"

    parser = DockerComposeParser(compose_file_path)
    return parser.get_service_config(service_name)
