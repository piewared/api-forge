"""Deployment target definitions and service URL resolution.

Ports and protocols are parsed from config.yaml defaults —
never hardcoded in deployment scripts.
"""

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse


class DeploymentTarget(Enum):
    DOCKER_COMPOSE_DEV = "docker-compose-dev"
    DOCKER_COMPOSE_PROD = "docker-compose-prod"
    KUBERNETES = "kubernetes"
    FLY_IO = "fly-io"


@dataclass(frozen=True)
class ServiceEndpoint:
    """A resolved service endpoint."""

    url: str


@dataclass(frozen=True)
class ServiceDefaults:
    """Service connection defaults extracted from config.yaml.

    Parsed from the ${VAR:-default} patterns so that port numbers
    and protocols are never duplicated in deployment code.
    """

    temporal_host: str
    temporal_port: int
    redis_scheme: str  # "redis" or "rediss"
    redis_host: str
    redis_port: int
    redis_path: str  # e.g. "/0"
    database_host: str
    database_port: int


def parse_service_defaults(
    config_path: Path = Path("config.yaml"),
) -> ServiceDefaults:
    """Parse default service URLs from config.yaml ${VAR:-default} patterns."""
    with open(config_path) as f:
        content = f.read()

    def _extract_default(var_name: str) -> str:
        pattern = rf"\$\{{{var_name}:-([^}}]+)\}}"
        match = re.search(pattern, content)
        return match.group(1) if match else ""

    temporal_default = _extract_default("TEMPORAL_URL")  # "temporal:7233"
    redis_default = _extract_default("REDIS_URL")  # "redis://localhost:6379"
    db_default = _extract_default("DATABASE_URL")  # "postgresql://..."

    # Parse Temporal (bare host:port)
    t_host, _, t_port = temporal_default.partition(":")

    # Parse Redis (URL format)
    r_parsed = urlparse(redis_default)

    # Parse Database (URL format)
    d_parsed = urlparse(db_default)

    return ServiceDefaults(
        temporal_host=t_host,
        temporal_port=int(t_port) if t_port else 7233,
        redis_scheme=r_parsed.scheme or "redis",
        redis_host=r_parsed.hostname or "localhost",
        redis_port=r_parsed.port or 6379,
        redis_path=r_parsed.path or "",
        database_host=d_parsed.hostname or "postgres",
        database_port=d_parsed.port or 5432,
    )


def resolve_fly_service_urls(
    defaults: ServiceDefaults,
    fly_app_base_name: str,
) -> dict[str, str]:
    """Resolve service URLs for Fly.io using .internal DNS.

    Returns dict of env var name -> URL string. Ports and protocols
    come from config.yaml defaults, hosts come from Fly app naming.
    """
    temporal_host = f"{fly_app_base_name}-temporal.internal"
    redis_host = f"{fly_app_base_name}-redis.internal"

    return {
        "TEMPORAL_URL": f"{temporal_host}:{defaults.temporal_port}",
        "REDIS_URL": (
            f"{defaults.redis_scheme}://{redis_host}"
            f":{defaults.redis_port}{defaults.redis_path}"
        ),
    }
