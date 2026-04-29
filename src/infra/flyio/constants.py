"""Fly.io deployment constants and configuration.

This module centralizes all Fly.io-specific constants, paths, and
configuration values used throughout Fly.io deployment operations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlyConstants:
    """Constants for Fly.io deployment.

    This class provides a centralized location for all Fly.io-related
    constants, making them easy to find, update, and test.

    All attributes are class-level and immutable.
    """

    # Fly Managed Postgres defaults
    DEFAULT_MPG_PLAN: str = "basic"
    DEFAULT_MPG_VOLUME_SIZE: int = 10  # GB
    DEFAULT_MPG_REGION: str = "iad"  # US East (Ashburn)

    # Available Fly.io regions (subset of most common)
    COMMON_REGIONS: tuple[str, ...] = (
        "iad",  # Ashburn, Virginia (US East)
        "lax",  # Los Angeles, California (US West)
        "ord",  # Chicago, Illinois (US Central)
        "sea",  # Seattle, Washington (US Northwest)
        "ewr",  # Secaucus, NJ (US Northeast)
        "lhr",  # London, UK (Europe)
        "ams",  # Amsterdam, Netherlands (Europe)
        "fra",  # Frankfurt, Germany (Europe)
        "cdg",  # Paris, France (Europe)
        "nrt",  # Tokyo, Japan (Asia)
        "sin",  # Singapore (Asia)
        "syd",  # Sydney, Australia (Oceania)
        "gru",  # São Paulo, Brazil (South America)
    )

    # Managed Postgres plans
    MPG_PLANS: tuple[str, ...] = (
        "basic",  # 1 shared CPU, 256MB RAM, 10GB storage
        "development",  # 1 shared CPU, 1GB RAM, 10GB storage
        "production",  # 2 dedicated CPUs, 4GB RAM, 40GB storage
        "production-xl",  # 4 dedicated CPUs, 8GB RAM, 80GB storage
    )

    # Timeouts
    PROXY_STARTUP_TIMEOUT: int = 30  # seconds
    COMMAND_TIMEOUT: int = 60  # seconds for most commands

    # Secret names (matching existing k8s secret structure)
    DATABASE_URL_SECRET: str = "DATABASE_URL"
    POSTGRES_PASSWORD_SECRET: str = "POSTGRES_PASSWORD"

    # Proxy settings
    DEFAULT_PROXY_PORT: int = 5432
    PROXY_LOCAL_PORT: int = 54321  # Different from k8s to avoid conflicts


# Default instance for convenience
DEFAULT_FLY_CONSTANTS = FlyConstants()
