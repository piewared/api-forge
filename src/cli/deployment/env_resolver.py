"""Target-aware environment variable resolver.

Replaces verbatim .env copying with target-specific resolution.
"""

from src.app.runtime.config.env_promotion import promote_env_vars


def resolve_env_for_target(
    env_vars: dict[str, str],
    env_mode: str = "production",
) -> dict[str, str]:
    """Promote vars, strip irrelevant prefixes, and clean up.

    Steps:
        1. Promote {env_mode}_* vars to plain keys
        2. Remove DEVELOPMENT_* vars (not relevant in production targets)
        3. Remove remaining PRODUCTION_* vars (already promoted to plain keys)
        4. Filter out placeholder values

    Args:
        env_vars: Raw environment variables from .env file(s).
        env_mode: Target environment mode (default "production").

    Returns:
        Clean dict ready for the target environment.
    """
    promoted = promote_env_vars(env_vars, env_mode)

    result = {}
    for key, value in promoted.items():
        # Skip vars with wrong-environment prefix
        if key.startswith("DEVELOPMENT_") or key.startswith("TEST_"):
            continue
        # Skip the PRODUCTION_* originals (plain keys already exist)
        if key.startswith("PRODUCTION_"):
            continue
        # Skip placeholders
        if not value or "CHANGE_ME" in value or "your-" in value.lower():
            continue
        result[key] = value

    return result
