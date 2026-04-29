"""Shared .env file parsing utility.

This module is the single authoritative implementation for parsing .env files.
It has no deployment-target-specific knowledge and may be imported by any layer.
"""

from pathlib import Path


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict.

    Handles comments, blank lines, and single/double quoted values.

    Args:
        path: Path to the .env file.

    Returns:
        Dictionary of environment variable name -> value.
    """
    env_vars: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]
                env_vars[key] = value
    return env_vars
