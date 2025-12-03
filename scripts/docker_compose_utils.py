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


def remove_temporal_from_docker_compose(content: str) -> str:
    """
    Remove Temporal services and dependencies from a Docker Compose file content.

    This function performs the following transformations:
    1. Removes all Temporal-related service blocks (temporal, temporal-web, temporal-schema-setup,
       temporal-admin-tools, temporal-namespace-init, worker)
    2. Removes temporal from depends_on blocks (both with conditions and list format)
    3. Removes Temporal volume definitions (temporal_data, temporal_postgres_data, temporal_certs)
    4. Removes postgres_temporal_pw from secrets sections
    5. Removes Temporal-related environment variables from other services
    6. Removes Temporal-related comments

    Args:
        content: The raw Docker Compose YAML content as a string

    Returns:
        The modified Docker Compose content with Temporal removed

    Example:
        >>> content = '''
        ... services:
        ...   temporal:
        ...     image: temporalio/auto-setup:1.28.1
        ...   app:
        ...     depends_on:
        ...       - temporal
        ... '''
        >>> result = remove_temporal_from_docker_compose(content)
        >>> 'temporal:' not in result
        True
    """
    # List of Temporal-related services to remove
    temporal_services = [
        "temporal-schema-setup",
        "temporal-admin-tools",
        "temporal-namespace-init",
        "temporal-web",
        "temporal",
        "worker",
    ]

    # Remove each Temporal service block
    # Match optional comment line, then service name at service level (2 spaces)
    # to the next service definition or to the end of the services section
    for service in temporal_services:
        # Handle comment before service (e.g., "  # Temporal Workflow Engine")
        content = re.sub(
            rf"(?:^  # (?:Temporal|Worker).*\n)?^  {re.escape(service)}:.*?(?=^  [\w-]+:|^volumes:|^networks:|^secrets:|\Z)",
            "",
            content,
            flags=re.DOTALL | re.MULTILINE,
        )

    # Remove temporal from depends_on blocks (with condition)
    # Handles patterns like:
    #   temporal:
    #     condition: service_healthy
    content = re.sub(
        r"      temporal(?:-[\w-]+)?:\s*\n\s+condition:.*?\n",
        "",
        content,
    )

    # Remove standalone depends_on: temporal lines (in list format)
    content = re.sub(
        r"^(\s+)-\s+temporal(?:-[\w-]+)?\s*$", "", content, flags=re.MULTILINE
    )

    # Remove Temporal volume definitions
    temporal_volumes = [
        "temporal_data",
        "temporal_postgres_data",
        "temporal_certs",
    ]
    for volume in temporal_volumes:
        content = re.sub(
            rf"  {volume}:.*?(?=\n  \w+:|\n\w+:|\Z)",
            "",
            content,
            flags=re.DOTALL,
        )

    # Remove postgres_temporal_pw from secrets lists in services
    content = re.sub(
        r"^(\s+)-\s+postgres_temporal_pw\s*$", "", content, flags=re.MULTILINE
    )

    # Remove postgres_temporal_pw secret definition from secrets section
    content = re.sub(
        r"^  postgres_temporal_pw:.*?(?=\n  \w+:|\n\w+:|\n\n|\Z)",
        "",
        content,
        flags=re.DOTALL | re.MULTILINE,
    )

    # Remove Temporal-related environment variables from remaining services
    # Handles patterns like:
    #   - DEVELOPMENT_TEMPORAL_URL=temporal:7233
    #   - TEMPORAL_ADDRESS=temporal:7233
    content = re.sub(
        r"^(\s+)-\s+(?:DEVELOPMENT_|PRODUCTION_)?TEMPORAL_(?:URL|ADDRESS|DB|VIS_DB|DB_USER)=.*$\n",
        "",
        content,
        flags=re.MULTILINE,
    )

    # Remove Temporal DB settings from postgres environment (in prod compose)
    # Handles patterns like:
    #   TEMPORAL_DB: ${TEMPORAL_DB:-temporal}
    content = re.sub(
        r"^\s+TEMPORAL_(?:DB|VIS_DB|DB_USER):.*$\n",
        "",
        content,
        flags=re.MULTILINE,
    )

    # Remove "# Temporal Workflow Engine" and similar comment lines
    content = re.sub(r"^  # Temporal.*\n", "", content, flags=re.MULTILINE)

    # Clean up empty depends_on blocks that might be left behind
    content = re.sub(
        r"    depends_on:\s*\n(?=    \w+:|\n  \w+:|^volumes:|^networks:|^secrets:|\Z)",
        "",
        content,
        flags=re.MULTILINE,
    )

    return content
