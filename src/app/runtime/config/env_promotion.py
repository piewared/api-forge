"""Single canonical implementation of environment variable prefix promotion.

All deployment paths (config_loader, Fly CLI, Helm) must use this module
instead of reimplementing the prefix-stripping logic.
"""


def promote_env_vars(
    env_vars: dict[str, str],
    env_mode: str = "production",
) -> dict[str, str]:
    """Promote prefixed env vars to their plain-key equivalents.

    PRODUCTION_DATABASE_URL -> DATABASE_URL (when env_mode="production").
    The promoted (plain) key WINS over any existing value for that key.
    Original prefixed keys are preserved for backward compatibility.

    Args:
        env_vars: Source environment variables.
        env_mode: Environment mode whose prefix to promote (e.g. "production").

    Returns:
        New dict with promoted keys added. Does NOT mutate input.
    """
    prefix = f"{env_mode.upper()}_"
    result = dict(env_vars)
    for key, value in env_vars.items():
        if key.startswith(prefix):
            plain_key = key[len(prefix) :]
            result[plain_key] = value
    return result
