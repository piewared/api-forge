"""Utility functions for manipulating Docker Compose files."""

import re


def remove_redis_from_docker_compose(content: str) -> str:
    """
    Remove Redis service and dependencies from a Docker Compose file content.

    This function performs the following transformations:
    1. Removes the Redis service block (at service level with 2-space indentation)
    2. Removes redis from depends_on blocks (both with conditions and list format)
    3. Removes redis volume definitions (redis_data and redis_backups)
    4. Removes redis_password from service secrets lists
    5. Removes redis_password secret definition from secrets section
    6. Removes Redis-related comments

    Args:
        content: The raw Docker Compose YAML content as a string

    Returns:
        The modified Docker Compose content with Redis removed

    Example:
        >>> content = '''
        ... services:
        ...   redis:
        ...     image: redis:7
        ...   app:
        ...     depends_on:
        ...       - redis
        ... '''
        >>> result = remove_redis_from_docker_compose(content)
        >>> 'redis:' not in result
        True
    """
    # Remove Redis service block (including any comment immediately before it)
    # Match optional comment line, then "  redis:" (exactly 2 spaces, at service level)
    # to the next service definition or to the end of the services section
    # Use ^ and MULTILINE to ensure we only match service-level redis (2 spaces at line start)
    # Note: [\w-]+ matches service names with hyphens (like temporal-schema-setup)
    content = re.sub(
        r"(?:^  # Redis.*\n)?^  redis:.*?(?=^  [\w-]+:|^volumes:|^networks:|^secrets:|\Z)",
        "",
        content,
        flags=re.DOTALL | re.MULTILINE,
    )

    # Remove redis from depends_on blocks (with condition)
    content = re.sub(r"      redis:\s*\n\s+condition:.*?\n", "", content)

    # Remove standalone depends_on: redis lines (in list format, not in comments)
    content = re.sub(r"^(\s+)-\s+redis\s*$", "", content, flags=re.MULTILINE)

    # Remove redis_data volume definition
    content = re.sub(
        r"  redis_data:.*?(?=\n  \w+:|\n\w+:|\Z)", "", content, flags=re.DOTALL
    )
    content = re.sub(
        r"  redis_backups:.*?(?=\n  \w+:|\n\w+:|\Z)",
        "",
        content,
        flags=re.DOTALL,
    )

    # Remove redis_password from secrets lists in services (e.g., "      - redis_password")
    content = re.sub(r"^(\s+)-\s+redis_password\s*$", "", content, flags=re.MULTILINE)

    # Remove redis_password secret definition from secrets section
    # Match "  redis_password:" through the file path line
    content = re.sub(
        r"^  # Redis password\s*\n\s+redis_password:.*?\n\s+file:.*?\n",
        "",
        content,
        flags=re.MULTILINE,
    )
    # Also handle case without comment
    content = re.sub(
        r"^  redis_password:.*?(?=\n  \w+:|\n\w+:|\n\n|\Z)",
        "",
        content,
        flags=re.DOTALL | re.MULTILINE,
    )

    # Remove "# Redis Cache/Session Store" comment lines
    content = re.sub(r"^  # Redis.*\n", "", content, flags=re.MULTILINE)

    return content
