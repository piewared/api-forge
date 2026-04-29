"""Authoritative secrets registry.

Every secret used by any deployment target is declared here ONCE.
Deployment adapters query this registry instead of maintaining parallel lists.
"""

from dataclasses import dataclass
from enum import Enum


class SecretScope(Enum):
    POSTGRES = "postgres-secrets"
    REDIS = "redis-secrets"
    APP = "app-secrets"


@dataclass(frozen=True)
class SecretEntry:
    """A single secret declaration with its deployment target scope."""

    name: str  # File name in infra/secrets/keys/ (e.g. "postgres_password")
    scope: SecretScope
    env_var: str  # Uppercased env var name (e.g. "POSTGRES_PASSWORD")
    targets: frozenset[str]  # {"docker-compose-prod", "kubernetes", "fly-io"}


SECRETS: tuple[SecretEntry, ...] = (
    # --- Postgres ---
    SecretEntry(
        "postgres_password",
        SecretScope.POSTGRES,
        "POSTGRES_PASSWORD",
        frozenset({"docker-compose-prod", "kubernetes"}),
    ),
    SecretEntry(
        "postgres_app_owner_pw",
        SecretScope.POSTGRES,
        "POSTGRES_APP_OWNER_PW",
        frozenset({"docker-compose-prod", "kubernetes", "fly-io"}),
    ),
    SecretEntry(
        "postgres_app_user_pw",
        SecretScope.POSTGRES,
        "POSTGRES_APP_USER_PW",
        frozenset({"docker-compose-prod", "kubernetes", "fly-io"}),
    ),
    SecretEntry(
        "postgres_app_ro_pw",
        SecretScope.POSTGRES,
        "POSTGRES_APP_RO_PW",
        frozenset({"docker-compose-prod", "kubernetes", "fly-io"}),
    ),
    SecretEntry(
        "postgres_temporal_pw",
        SecretScope.POSTGRES,
        "POSTGRES_TEMPORAL_PW",
        frozenset({"docker-compose-prod", "kubernetes"}),
    ),
    # --- Redis ---
    SecretEntry(
        "redis_password",
        SecretScope.REDIS,
        "REDIS_PASSWORD",
        frozenset({"docker-compose-prod", "kubernetes", "fly-io"}),
    ),
    # --- App ---
    SecretEntry(
        "session_signing_secret",
        SecretScope.APP,
        "SESSION_SIGNING_SECRET",
        frozenset({"docker-compose-prod", "kubernetes", "fly-io"}),
    ),
    SecretEntry(
        "csrf_signing_secret",
        SecretScope.APP,
        "CSRF_SIGNING_SECRET",
        frozenset({"docker-compose-prod", "kubernetes", "fly-io"}),
    ),
    SecretEntry(
        "oidc_google_client_secret",
        SecretScope.APP,
        "OIDC_GOOGLE_CLIENT_SECRET",
        frozenset({"docker-compose-prod", "kubernetes", "fly-io"}),
    ),
    SecretEntry(
        "oidc_microsoft_client_secret",
        SecretScope.APP,
        "OIDC_MICROSOFT_CLIENT_SECRET",
        frozenset({"docker-compose-prod", "kubernetes", "fly-io"}),
    ),
    SecretEntry(
        "oidc_keycloak_client_secret",
        SecretScope.APP,
        "OIDC_KEYCLOAK_CLIENT_SECRET",
        frozenset({"docker-compose-prod", "kubernetes"}),
    ),
)


def get_secrets_for_target(target: str) -> list[SecretEntry]:
    """Return all secrets relevant to a deployment target."""
    return [s for s in SECRETS if target in s.targets]


def get_fly_secret_names() -> list[str]:
    """Return secret file names needed by Fly.io deployments."""
    return [s.name for s in get_secrets_for_target("fly-io")]
