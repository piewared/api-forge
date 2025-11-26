"""Keycloak Admin REST API client."""

from typing import Any, cast
from urllib.parse import urljoin

import requests  # type: ignore[import-untyped]


class KeycloakClient:
    """Low-level Keycloak Admin REST API client.

    This class handles all HTTP communication with the Keycloak Admin API.
    It provides a clean interface for CRUD operations on Keycloak resources.
    """

    def __init__(self, base_url: str = "http://localhost:8080", timeout: int = 30):
        """Initialize the Keycloak client.

        Args:
            base_url: Base URL of the Keycloak server
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.access_token: str | None = None

    def authenticate(self, username: str = "admin", password: str = "admin") -> str:
        """Authenticate with Keycloak and get an admin access token.

        Args:
            username: Admin username
            password: Admin password

        Returns:
            Access token string

        Raises:
            requests.RequestException: If authentication fails
        """
        token_url = urljoin(
            self.base_url, "/realms/master/protocol/openid-connect/token"
        )

        data = {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": username,
            "password": password,
        }

        response = requests.post(token_url, data=data, timeout=self.timeout)
        response.raise_for_status()

        token_data = response.json()
        self.access_token = token_data["access_token"]
        if not self.access_token:
            raise ValueError("Failed to obtain access token from Keycloak")
        return self.access_token

    def _get_headers(self) -> dict[str, str]:
        """Get standard headers for authenticated requests."""
        if not self.access_token:
            msg = "Not authenticated. Call authenticate() first."
            raise ValueError(msg)

        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    # Realm Management
    def get_realm(self, realm_name: str) -> dict[str, Any] | None:
        """Get realm configuration.

        Args:
            realm_name: Name of the realm

        Returns:
            Realm configuration dict or None if not found
        """
        url = urljoin(self.base_url, f"/admin/realms/{realm_name}")

        response = requests.get(url, headers=self._get_headers(), timeout=self.timeout)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    def create_realm(self, realm_config: dict[str, Any]) -> bool:
        """Create a new realm.

        Args:
            realm_config: Realm configuration dictionary

        Returns:
            True if created successfully, False otherwise
        """
        url = urljoin(self.base_url, "/admin/realms")

        response = requests.post(
            url, json=realm_config, headers=self._get_headers(), timeout=self.timeout
        )

        return bool(response.status_code == 201)

    # Client Management
    def get_clients(
        self, realm_name: str, client_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Get clients in a realm.

        Args:
            realm_name: Name of the realm
            client_id: Optional client ID to filter by

        Returns:
            List of client configurations
        """
        url = urljoin(self.base_url, f"/admin/realms/{realm_name}/clients")

        params = {}
        if client_id:
            params["clientId"] = client_id

        response = requests.get(
            url, headers=self._get_headers(), params=params, timeout=self.timeout
        )
        response.raise_for_status()

        return cast(list[dict[str, Any]], response.json())

    def create_client(self, realm_name: str, client_config: dict[str, Any]) -> bool:
        """Create a new client in a realm.

        Args:
            realm_name: Name of the realm
            client_config: Client configuration dictionary

        Returns:
            True if created successfully, False otherwise
        """
        url = urljoin(self.base_url, f"/admin/realms/{realm_name}/clients")

        response = requests.post(
            url, json=client_config, headers=self._get_headers(), timeout=self.timeout
        )

        return bool(response.status_code == 201)

    def update_client(
        self, realm_name: str, client_uuid: str, client_config: dict[str, Any]
    ) -> bool:
        """Update an existing client.

        Args:
            realm_name: Name of the realm
            client_uuid: UUID of the client
            client_config: Updated client configuration

        Returns:
            True if updated successfully, False otherwise
        """
        url = urljoin(
            self.base_url, f"/admin/realms/{realm_name}/clients/{client_uuid}"
        )

        response = requests.put(
            url, json=client_config, headers=self._get_headers(), timeout=self.timeout
        )

        return bool(response.status_code == 204)

    # User Management
    def get_users(
        self, realm_name: str, username: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get users in a realm.

        Args:
            realm_name: Name of the realm
            username: Optional username to filter by (exact match)
            limit: Maximum number of users to return

        Returns:
            List of user dictionaries
        """
        url = urljoin(self.base_url, f"/admin/realms/{realm_name}/users")

        params: dict[str, Any] = {"max": limit}
        if username:
            params["username"] = username
            params["exact"] = True

        response = requests.get(
            url, headers=self._get_headers(), params=params, timeout=self.timeout
        )
        response.raise_for_status()

        return cast(list[dict[str, Any]], response.json())

    def create_user(self, realm_name: str, user_data: dict[str, Any]) -> bool:
        """Create a new user in a realm.

        Args:
            realm_name: Name of the realm
            user_data: User configuration dictionary

        Returns:
            True if created successfully, False otherwise
        """
        url = urljoin(self.base_url, f"/admin/realms/{realm_name}/users")

        response = requests.post(
            url, json=user_data, headers=self._get_headers(), timeout=self.timeout
        )

        return bool(response.status_code == 201)

    def delete_user(self, realm_name: str, user_id: str) -> bool:
        """Delete a user from a realm.

        Args:
            realm_name: Name of the realm
            user_id: ID of the user to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        url = urljoin(self.base_url, f"/admin/realms/{realm_name}/users/{user_id}")

        response = requests.delete(
            url, headers=self._get_headers(), timeout=self.timeout
        )

        return bool(response.status_code == 204)

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
        url = urljoin(
            self.base_url, f"/admin/realms/{realm_name}/users/{user_id}/reset-password"
        )

        password_data = {
            "type": "password",
            "value": new_password,
            "temporary": temporary,
        }

        response = requests.put(
            url, json=password_data, headers=self._get_headers(), timeout=self.timeout
        )

        return bool(response.status_code == 204)

    # Convenience Methods
    def get_client_by_id(
        self, realm_name: str, client_id: str
    ) -> dict[str, Any] | None:
        """Get a client by its client ID.

        Args:
            realm_name: Name of the realm
            client_id: Client ID to search for

        Returns:
            Client configuration dict or None if not found
        """
        clients = self.get_clients(realm_name, client_id)
        return clients[0] if clients else None

    def get_user_by_username(
        self, realm_name: str, username: str
    ) -> dict[str, Any] | None:
        """Get a user by username.

        Args:
            realm_name: Name of the realm
            username: Username to search for

        Returns:
            User dict or None if not found
        """
        users = self.get_users(realm_name, username)
        return users[0] if users else None

    def realm_exists(self, realm_name: str) -> bool:
        """Check if a realm exists.

        Args:
            realm_name: Name of the realm to check

        Returns:
            True if realm exists, False otherwise
        """
        return self.get_realm(realm_name) is not None

    def client_exists(self, realm_name: str, client_id: str) -> bool:
        """Check if a client exists in a realm.

        Args:
            realm_name: Name of the realm
            client_id: Client ID to check

        Returns:
            True if client exists, False otherwise
        """
        return self.get_client_by_id(realm_name, client_id) is not None

    def user_exists(self, realm_name: str, username: str) -> bool:
        """Check if a user exists in a realm.

        Args:
            realm_name: Name of the realm
            username: Username to check

        Returns:
            True if user exists, False otherwise
        """
        return self.get_user_by_username(realm_name, username) is not None
