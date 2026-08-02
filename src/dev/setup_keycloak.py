#!/usr/bin/env python3
"""Keycloak setup script for development environment."""

import os
import sys
import time
from typing import Any, cast

import requests  # type: ignore[import-untyped]

from .keycloak_client import KeycloakClient

# Keycloak puts only "account" in the `aud` claim of an access token unless the
# client is given an audience mapper. The API validates `aud` against
# config.jwt.audiences (config.yaml -> "${JWT_AUDIENCE:-api://default}"), so
# without this mapper the dev realm mints tokens its own API rejects and the
# Bearer-JWT path cannot be exercised at all.
#
# Read from the same environment variable config.yaml interpolates so the realm
# and the API stay aligned when an operator overrides the default.
DEFAULT_API_AUDIENCE = "api://default"
AUDIENCE_MAPPER_NAME = "api-audience"


def get_api_audience() -> str:
    """Return the audience the API expects in incoming access tokens."""
    return os.environ.get("JWT_AUDIENCE") or DEFAULT_API_AUDIENCE


def build_audience_mapper(audience: str) -> dict[str, Any]:
    """Build the protocol mapper that stamps `audience` into the access token."""
    return {
        "name": AUDIENCE_MAPPER_NAME,
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "consentRequired": False,
        "config": {
            "included.custom.audience": audience,
            "access.token.claim": "true",
            "id.token.claim": "false",
            "introspection.token.claim": "true",
        },
    }


class KeycloakSetup:
    """Keycloak configuration setup for development.

    This class handles the business logic of setting up a Keycloak instance
    for development use, including creating realms, clients, and test users.
    """

    def __init__(self, base_url: str = "http://localhost:8080"):
        """Initialize the Keycloak setup.

        Args:
            base_url: Base URL of the Keycloak server
        """
        self.client = KeycloakClient(base_url)
        self.base_url = base_url

    def get_admin_token(self) -> str:
        """Authenticate with Keycloak admin credentials.

        Returns:
            Access token string

        Raises:
            requests.RequestException: If authentication fails
        """
        return self.client.authenticate("admin", "admin")

    def create_realm(self, realm_name: str = "test-realm") -> None:
        """Create a test realm if it doesn't exist.

        Args:
            realm_name: Name of the realm to create
        """
        if self.client.realm_exists(realm_name):
            print(f"✅ Realm '{realm_name}' already exists")
            return

        realm_config = {
            "realm": realm_name,
            "enabled": True,
            "displayName": "Test Realm for OIDC Development",
            "loginWithEmailAllowed": True,
            "duplicateEmailsAllowed": False,
            "rememberMe": True,
            "verifyEmail": False,
            "resetPasswordAllowed": True,
            "editUsernameAllowed": True,
            "bruteForceProtected": False,
        }

        if self.client.create_realm(realm_config):
            print(f"✅ Created realm '{realm_name}'")
        else:
            print(f"❌ Failed to create realm '{realm_name}'")
            sys.exit(1)

    def create_client(
        self, realm_name: str = "test-realm", client_id: str = "test-client"
    ) -> None:
        """Create a test client for OIDC flows if it doesn't exist.

        Args:
            realm_name: Name of the realm
            client_id: ID of the client to create
        """
        if self.client.client_exists(realm_name, client_id):
            print(f"✅ Client '{client_id}' already exists")
            return

        client_config = {
            "clientId": client_id,
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "standardFlowEnabled": True,  # Authorization Code Flow
            "implicitFlowEnabled": False,
            "directAccessGrantsEnabled": True,  # Resource Owner Password Credentials
            "serviceAccountsEnabled": True,
            "authorizationServicesEnabled": False,
            "redirectUris": [
                "http://localhost:8000/auth/web/callback",
                "http://localhost:3000/*",
                "http://localhost:3001/*",
            ],
            "webOrigins": [
                "http://localhost:8000",
                "http://localhost:3000",
                "http://localhost:3001",
            ],
            "attributes": {
                "pkce.code.challenge.method": "S256",
                "post.logout.redirect.uris": "http://localhost:8000/*",
            },
        }

        if self.client.create_client(realm_name, client_config):
            print(f"✅ Created client '{client_id}'")

            # Set the client secret
            client = self.client.get_client_by_id(realm_name, client_id)
            if client:
                self.set_client_secret(realm_name, client["id"], "test-client-secret")
        else:
            print(f"❌ Failed to create client '{client_id}'")
            sys.exit(1)

    def ensure_audience_mapper(
        self, realm_name: str = "test-realm", client_id: str = "test-client"
    ) -> None:
        """Ensure the client stamps the API's expected audience into its tokens.

        Runs for both freshly created and pre-existing clients so realms seeded
        by an earlier version of this script are repaired in place. Idempotent:
        the mapper is only added when absent.

        Args:
            realm_name: Name of the realm
            client_id: ID of the client
        """
        client = self.client.get_client_by_id(realm_name, client_id)
        if not client:
            print(f"❌ Cannot add audience mapper: client '{client_id}' not found")
            return

        audience = get_api_audience()
        mappers = self.client.get_protocol_mappers(realm_name, client["id"])

        if any(mapper.get("name") == AUDIENCE_MAPPER_NAME for mapper in mappers):
            print(f"✅ Audience mapper already present (aud '{audience}')")
            return

        if self.client.create_protocol_mapper(
            realm_name, client["id"], build_audience_mapper(audience)
        ):
            print(f"✅ Added audience mapper (aud '{audience}')")
        else:
            print(f"❌ Failed to add audience mapper for '{audience}'")

    def set_client_secret(self, realm_name: str, client_uuid: str, secret: str) -> None:
        """Set the secret for a client.

        Args:
            realm_name: Name of the realm
            client_uuid: UUID of the client
            secret: Secret to set
        """
        update_config = {"secret": secret}

        if self.client.update_client(realm_name, client_uuid, update_config):
            print("✅ Set client secret")
        else:
            print("❌ Failed to set client secret")

    def create_test_users(self, realm_name: str = "test-realm") -> None:
        """Create default test users if they don't exist.

        Args:
            realm_name: Name of the realm
        """
        test_users = [
            {
                "username": "testuser1",
                "email": "testuser1@example.com",
                "firstName": "Test",
                "lastName": "User One",
                "enabled": True,
                "emailVerified": True,
                "credentials": [
                    {
                        "type": "password",
                        "value": "password123",
                        "temporary": False,
                    }
                ],
            },
            {
                "username": "testuser2",
                "email": "testuser2@example.com",
                "firstName": "Test",
                "lastName": "User Two",
                "enabled": True,
                "emailVerified": True,
                "credentials": [
                    {
                        "type": "password",
                        "value": "password123",
                        "temporary": False,
                    }
                ],
            },
        ]

        for user in test_users:
            username: str = cast(str, user["username"])

            if self.client.user_exists(realm_name, username):
                print(f"✅ User '{username}' already exists")
                continue

            if self.client.create_user(realm_name, user):
                print(f"✅ Created user '{username}'")
            else:
                print(f"❌ Failed to create user '{username}'")

    def print_configuration(
        self, realm_name: str = "test-realm", client_id: str = "test-client"
    ) -> None:
        """Print the configuration details for the setup.

        Args:
            realm_name: Name of the realm
            client_id: ID of the client
        """
        print("\n" + "=" * 60)
        print("🔧 KEYCLOAK CONFIGURATION")
        print("=" * 60)
        print(f"Issuer URL: {self.base_url}/realms/{realm_name}")
        print(
            f"Authorization Endpoint: {self.base_url}/realms/{realm_name}/protocol/openid-connect/auth"
        )
        print(
            f"Token Endpoint: {self.base_url}/realms/{realm_name}/protocol/openid-connect/token"
        )
        print(
            f"Userinfo Endpoint: {self.base_url}/realms/{realm_name}/protocol/openid-connect/userinfo"
        )
        print(
            f"JWKS URI: {self.base_url}/realms/{realm_name}/protocol/openid-connect/certs"
        )
        print(
            f"End Session Endpoint: {self.base_url}/realms/{realm_name}/protocol/openid-connect/logout"
        )
        print("")
        print(f"Client ID: {client_id}")
        print("Client Secret: test-client-secret")
        print("Redirect URI: http://localhost:8000/auth/web/callback")
        print("")
        print("Environment Variables for .env:")
        print(f"OIDC_DEFAULT_CLIENT_ID={client_id}")
        print("OIDC_DEFAULT_CLIENT_SECRET=test-client-secret")
        print(f"OIDC_DEFAULT_ISSUER={self.base_url}/realms/{realm_name}")
        print(
            f"OIDC_DEFAULT_AUTHORIZATION_ENDPOINT={self.base_url}/realms/{realm_name}/protocol/openid-connect/auth"
        )
        print(
            f"OIDC_DEFAULT_TOKEN_ENDPOINT={self.base_url}/realms/{realm_name}/protocol/openid-connect/token"
        )
        print(
            f"OIDC_DEFAULT_USERINFO_ENDPOINT={self.base_url}/realms/{realm_name}/protocol/openid-connect/userinfo"
        )
        print(
            f"OIDC_DEFAULT_JWKS_URI={self.base_url}/realms/{realm_name}/protocol/openid-connect/certs"
        )
        print(
            f"OIDC_DEFAULT_END_SESSION_ENDPOINT={self.base_url}/realms/{realm_name}/protocol/openid-connect/logout"
        )
        print("OIDC_DEFAULT_REDIRECT_URI=http://localhost:8000/auth/web/callback")
        print(f"JWT_AUDIENCE={get_api_audience()}")
        print("=" * 60)

    def setup_all(self) -> None:
        """Run the complete Keycloak setup process."""
        try:
            print("🔐 Getting admin token...")
            self.get_admin_token()

            print("🏢 Creating test realm...")
            self.create_realm()

            print("📱 Creating test client...")
            self.create_client()

            print("🎯 Ensuring audience mapper...")
            self.ensure_audience_mapper()

            print("👥 Creating test users...")
            self.create_test_users()

            self.print_configuration()

        except requests.exceptions.RequestException as e:
            print(f"❌ Error communicating with Keycloak: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            sys.exit(1)

    # Delegate user management methods to the client for backward compatibility
    def list_users(
        self, realm_name: str = "test-realm", limit: int = 100
    ) -> list[dict[str, Any]]:
        """List users in a realm.

        Args:
            realm_name: Name of the realm
            limit: Maximum number of users to return

        Returns:
            List of user dictionaries
        """
        return self.client.get_users(realm_name, limit=limit)

    def get_user_by_username(
        self, realm_name: str, username: str
    ) -> dict[str, Any] | None:
        """Get a user by username.

        Args:
            realm_name: Name of the realm
            username: Username to search for

        Returns:
            User dictionary or None if not found
        """
        return self.client.get_user_by_username(realm_name, username)

    def create_user(self, realm_name: str, user_data: dict[str, Any]) -> bool:
        """Create a new user in a realm.

        Args:
            realm_name: Name of the realm
            user_data: User configuration dictionary

        Returns:
            True if created successfully, False otherwise
        """
        return self.client.create_user(realm_name, user_data)

    def delete_user(self, realm_name: str, user_id: str) -> bool:
        """Delete a user from a realm.

        Args:
            realm_name: Name of the realm
            user_id: ID of the user to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        return self.client.delete_user(realm_name, user_id)

    def reset_user_password(
        self, realm_name: str, user_id: str, new_password: str, temporary: bool = False
    ) -> bool:
        """Reset a user's password.

        Args:
            realm_name: Name of the realm
            user_id: ID of the user
            new_password: New password to set
            temporary: Whether the password should be temporary

        Returns:
            True if password reset successfully, False otherwise
        """
        return self.client.reset_user_password(
            realm_name, user_id, new_password, temporary
        )


def main() -> None:
    """Main entry point."""
    print("🔧 Configuring Keycloak for development...")

    setup = KeycloakSetup()

    # Wait a bit for Keycloak to be fully ready
    time.sleep(5)

    setup.setup_all()

    print("\n✅ Keycloak configuration complete!")


if __name__ == "__main__":
    main()
