"""Unit tests for secrets_registry module."""

from src.app.runtime.config.secrets_registry import (
    SECRETS,
    SecretScope,
    get_fly_secret_names,
    get_secrets_for_target,
)


class TestSecretsRegistry:
    """Verify the canonical secrets registry."""

    def test_all_secrets_have_non_empty_targets(self):
        for secret in SECRETS:
            assert secret.targets, f"Secret {secret.name} has no targets"

    def test_all_secrets_have_env_var(self):
        for secret in SECRETS:
            assert secret.env_var == secret.name.upper(), (
                f"Secret {secret.name}: env_var {secret.env_var} "
                f"doesn't match uppercase name {secret.name.upper()}"
            )

    def test_get_fly_secret_names_excludes_non_fly_secrets(self):
        fly_names = get_fly_secret_names()
        # postgres_password is not needed on Fly.io (managed Postgres)
        assert "postgres_password" not in fly_names
        # keycloak is dev-only, not on Fly.io
        assert "oidc_keycloak_client_secret" not in fly_names

    def test_get_fly_secret_names_includes_expected(self):
        fly_names = get_fly_secret_names()
        expected = {
            "session_signing_secret",
            "csrf_signing_secret",
            "oidc_google_client_secret",
            "oidc_microsoft_client_secret",
            "redis_password",
            "postgres_app_user_pw",
            "postgres_app_owner_pw",
            "postgres_app_ro_pw",
        }
        assert set(fly_names) == expected

    def test_get_secrets_for_target_kubernetes(self):
        k8s_secrets = get_secrets_for_target("kubernetes")
        k8s_names = {s.name for s in k8s_secrets}
        # K8s gets everything including postgres_password and keycloak
        assert "postgres_password" in k8s_names
        assert "oidc_keycloak_client_secret" in k8s_names

    def test_get_secrets_for_unknown_target_returns_empty(self):
        assert get_secrets_for_target("nonexistent") == []

    def test_secret_scopes_are_valid(self):
        for secret in SECRETS:
            assert isinstance(secret.scope, SecretScope)
