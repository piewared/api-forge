"""Fly.io secrets synchronization."""

# Secrets to sync from infra/secrets/keys/ to Fly.io
# Sourced from the canonical secrets registry instead of a hardcoded list.
from src.app.runtime.config.env_promotion import promote_env_vars
from src.app.runtime.config.secrets_registry import get_fly_secret_names
from src.cli.shared.console import console
from src.infra.flyio import FlyCtlControllerSync
from src.infra.secrets import SecretKind, get_secrets_manager

from .settings import _load_env_file

FLY_SECRETS = get_fly_secret_names()

# Hardcoded env vars for Fly.io deployments
# APP_ENVIRONMENT must be "production" so the app uses production config
FLY_HARDCODED_ENV_VARS = {
    "APP_ENVIRONMENT": "production",
}


def _is_placeholder_value(value: str) -> bool:
    """True if the value is empty or matches a known placeholder marker.

    Placeholder values (``CHANGE_ME``, ``your-…``) are present in the shipped
    ``.env.example`` to nudge users; we never want to push them to Fly as
    real secrets.
    """
    if not value:
        return True
    return "CHANGE_ME" in value or "your-" in value.lower()


def _sync_secrets(
    controller: FlyCtlControllerSync,
    app_name: str,
    *,
    force: bool = False,
) -> bool:
    """Sync secrets to Fly.io app.

    Reads secrets from the local secrets manager and sets them as Fly.io secrets.

    Args:
        controller: FlyCtlControllerSync instance
        app_name: Name of the Fly.io app
        force: If True, set all secrets even if they already exist

    Returns:
        True if secrets were synced successfully
    """
    manager = get_secrets_manager()

    # Get currently set secrets on Fly.io
    existing_secrets = set(controller.secrets_list(app_name))

    # Collect secrets to set
    secrets_to_set: dict[str, str] = {}
    missing_secrets: list[str] = []

    # 1. Sync secrets from infra/secrets/keys/
    for secret_name in FLY_SECRETS:
        env_var = secret_name.upper()

        # Check if secret file exists locally
        if not manager.exists(secret_name, SecretKind.KEY):
            missing_secrets.append(secret_name)
            continue

        # Read secret value
        value = manager.read(secret_name, SecretKind.KEY)
        if not value:
            missing_secrets.append(secret_name)
            continue

        # Only set if forced or not already set
        if force or env_var not in existing_secrets:
            secrets_to_set[env_var] = value.strip()

    # 2. Sync all env vars from .env file
    env_vars = _load_env_file(include_fly_overrides=True)
    for env_var, value in env_vars.items():
        if _is_placeholder_value(value):
            continue
        if force or env_var not in existing_secrets:
            secrets_to_set[env_var] = value

    # 2b. Promote PRODUCTION_* vars: PRODUCTION_DATABASE_URL -> DATABASE_URL.
    # Ensures the app receives the plain form that config_data.py expects.
    promoted = promote_env_vars(env_vars, "production")
    for key, value in promoted.items():
        if key in env_vars:
            continue  # Already handled above; skip to avoid re-adding.
        if _is_placeholder_value(value):
            continue
        secrets_to_set[key] = value

    # 3. Set hardcoded env vars (e.g., APP_ENVIRONMENT=production) - last so they win
    for env_var, value in FLY_HARDCODED_ENV_VARS.items():
        if force or env_var not in existing_secrets:
            secrets_to_set[env_var] = value

    # Report missing secrets
    if missing_secrets:
        console.warn(f"Missing secrets: {', '.join(missing_secrets)}")
        console.info("Generate secrets with: uv run api-forge-cli secrets generate")

    if not secrets_to_set:
        if existing_secrets:
            console.debug("All secrets already set on Fly.io")
        return True

    # Set secrets on Fly.io (staging to avoid redeploy)
    console.debug(
        f"Setting {len(secrets_to_set)} secret(s): {', '.join(secrets_to_set.keys())}"
    )

    result = controller.secrets_set(app_name, secrets_to_set, stage=True)

    if result.success:
        console.debug(f"Secrets staged for {app_name}")
        return True
    else:
        console.error(f"Failed to set secrets: {result.stderr}")
        return False
