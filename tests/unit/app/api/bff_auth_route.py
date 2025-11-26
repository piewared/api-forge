from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import HTTPException, status

from src.app.core.models.session import AuthSession


class TestBFFAuthenticationRouter:
    """Test BFF authentication router endpoints."""

    def test_initiate_login_success(self, auth_test_client):
        """Test successful login initiation."""
        with (
            patch(
                "src.app.core.services.oidc_client_service.generate_pkce_pair"
            ) as mock_pkce,
            patch(
                "src.app.core.services.oidc_client_service.generate_state"
            ) as mock_state,
            patch(
                "src.app.core.services.session_service.create_auth_session"
            ) as mock_create_session,
        ):
            mock_pkce.return_value = ("test-verifier", "test-challenge")
            mock_state.return_value = "test-state"
            mock_create_session.return_value = "auth-session-123"

            response = auth_test_client.get("/auth/web/login", follow_redirects=False)

            assert response.status_code == status.HTTP_302_FOUND

            # Verify redirect to OIDC provider
            location = response.headers["Location"]
            parsed = urlparse(location)
            query_params = parse_qs(parsed.query)

            assert parsed.hostname == "mock-provider.test"
            assert query_params["client_id"][0] == "test-client-id"
            assert query_params["response_type"][0] == "code"
            assert query_params["state"][0] == "test-state"
            assert query_params["code_challenge"][0] == "test-challenge"

    def test_callback_success(
        self,
        auth_test_client,
        test_auth_session: AuthSession,
        test_user,
        test_token_response,
    ):
        """Test successful callback handling."""
        with (
            patch(
                "src.app.core.services.session_service.get_auth_session",
                return_value=test_auth_session,
            ),
            patch(
                "src.app.core.services.oidc_client_service.exchange_code_for_tokens",
                return_value=test_token_response,
            ),
            patch(
                "src.app.core.services.session_service.provision_user_from_claims",
                return_value=test_user,
            ),
            patch("src.app.core.services.session_service.delete_auth_session"),
            patch(
                "src.app.core.security.hash_client_fingerprint",
                return_value=test_auth_session.client_fingerprint_hash,
            ),
        ):
            # Set auth session cookie
            auth_test_client.cookies.set("auth_session_id", test_auth_session.id)

            response = auth_test_client.get(
                f"/auth/web/callback?code=test-code&state={test_auth_session.state}",
                follow_redirects=False,
            )

            assert response.status_code == status.HTTP_302_FOUND
            assert response.headers["Location"] == test_auth_session.return_to

    def test_callback_invalid_state(self, auth_test_client, test_auth_session):
        """Test callback with invalid state parameter."""
        with patch(
            "src.app.core.services.session_service.get_auth_session",
            return_value=test_auth_session,
        ):
            auth_test_client.cookies.set("auth_session_id", test_auth_session.id)

            response = auth_test_client.get(
                "/auth/web/callback?code=test-code&state=wrong-state",
                follow_redirects=False,
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_callback_missing_session(self, auth_test_client):
        """Test callback without auth session."""
        response = auth_test_client.get(
            "/auth/web/callback?code=test-code&state=test-state", follow_redirects=False
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_me_endpoint_with_session(
        self, auth_test_client, test_user_session, test_user
    ):
        """Test /me endpoint with valid session."""
        with (
            patch(
                "src.app.api.http.deps.get_user_session", return_value=test_user_session
            ),
            patch(
                "src.app.entities.core.user.UserRepository.get", return_value=test_user
            ),
        ):
            auth_test_client.cookies.set("user_session_id", test_user_session.id)

            response = auth_test_client.get("/auth/web/me")

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["user"]["id"] == test_user.id
            assert data["user"]["email"] == test_user.email
            assert data["authenticated"] is True

    def test_me_endpoint_without_session(self, auth_test_client):
        """Test /me endpoint without session."""
        response = auth_test_client.get("/auth/web/me")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["authenticated"] is False
        assert data["user"] is None

    def test_logout_success(self, auth_test_client, test_user_session):
        """Test successful logout."""
        with (
            patch(
                "src.app.core.services.session_service.get_user_session",
                return_value=test_user_session,
            ),
            patch(
                "src.app.core.services.session_service.delete_user_session"
            ) as mock_delete,
        ):
            auth_test_client.cookies.set("user_session_id", test_user_session.id)

            response = auth_test_client.post("/auth/web/logout")

        assert response.status_code == status.HTTP_200_OK
        mock_delete.assert_called_once_with(test_user_session.id)

    def test_callback_with_error_parameter(self, auth_test_client, test_auth_session):
        """Test callback with error parameter from OIDC provider."""

        with patch(
            "src.app.core.services.session_service.get_auth_session",
            return_value=test_auth_session,
        ):
            auth_test_client.cookies.set("auth_session_id", test_auth_session.id)

            response = auth_test_client.get(
                f"/auth/web/callback?error=access_denied&error_description=User%20denied%20access&state={test_auth_session.state}",
                follow_redirects=False,
            )

            # The specific status code depends on FastAPI's validation behavior
            assert response.status_code in [
                400,
                422,
            ]  # Either bad request or unprocessable entity
            if response.status_code == 400:
                assert "Authorization failed" in response.text

    def test_callback_missing_code_parameter(self, auth_test_client, test_auth_session):
        """Test callback without required code parameter."""
        with patch(
            "src.app.core.services.session_service.get_auth_session",
            return_value=test_auth_session,
        ):
            auth_test_client.cookies.set("auth_session_id", test_auth_session.id)

            response = auth_test_client.get(
                f"/auth/web/callback?state={test_auth_session.state}",
                follow_redirects=False,
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert "Missing authorization code" in response.text

    def test_callback_token_exchange_failure(self, auth_test_client, test_auth_session):
        """Test callback when token exchange fails."""
        with (
            patch(
                "src.app.core.services.session_service.get_auth_session",
                return_value=test_auth_session,
            ),
            patch(
                "src.app.core.services.oidc_client_service.exchange_code_for_tokens",
                side_effect=httpx.HTTPStatusError(
                    "Token exchange failed", request=Mock(), response=Mock()
                ),
            ),
        ):
            auth_test_client.cookies.set("auth_session_id", test_auth_session.id)

            response = auth_test_client.get(
                f"/auth/web/callback?code=test-code&state={test_auth_session.state}",
                follow_redirects=False,
            )

            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_callback_user_claims_failure(
        self, auth_test_client, test_auth_session, test_token_response
    ):
        """Test callback when user claims extraction fails."""
        with (
            patch(
                "src.app.core.services.session_service.get_auth_session",
                return_value=test_auth_session,
            ),
            patch(
                "src.app.core.services.oidc_client_service.exchange_code_for_tokens",
                return_value=test_token_response,
            ),
            patch(
                "src.app.core.services.oidc_client_service.get_user_claims",
                side_effect=HTTPException(status_code=401, detail="Invalid ID token"),
            ),
        ):
            auth_test_client.cookies.set("auth_session_id", test_auth_session.id)

            response = auth_test_client.get(
                f"/auth/web/callback?code=test-code&state={test_auth_session.state}",
                follow_redirects=False,
            )

            # Error handling may convert HTTPException to 500 in the router
            assert response.status_code in [401, 500]

    def test_callback_user_provisioning_failure(
        self, auth_test_client, test_auth_session, test_token_response
    ):
        """Test callback when user provisioning fails."""
        with (
            patch(
                "src.app.core.services.session_service.get_auth_session",
                return_value=test_auth_session,
            ),
            patch(
                "src.app.core.services.oidc_client_service.exchange_code_for_tokens",
                return_value=test_token_response,
            ),
            patch(
                "src.app.core.services.session_service.provision_user_from_claims",
                side_effect=Exception("Database connection failed"),
            ),
        ):
            auth_test_client.cookies.set("auth_session_id", test_auth_session.id)

            response = auth_test_client.get(
                f"/auth/web/callback?code=test-code&state={test_auth_session.state}",
                follow_redirects=False,
            )

            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_me_endpoint_with_invalid_session(self, auth_test_client):
        """Test /me endpoint with corrupted or invalid session."""
        # Set invalid session cookie
        auth_test_client.cookies.set("user_session_id", "invalid-session-id-12345")

        with patch("src.app.api.http.deps.get_user_session", return_value=None):
            response = auth_test_client.get("/auth/web/me")

            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["authenticated"] is False
            assert data["user"] is None

    def test_logout_without_session(self, auth_test_client):
        """Test logout without active session."""
        with patch(
            "src.app.core.services.session_service.get_user_session",
            return_value=None,
        ):
            response = auth_test_client.post("/auth/web/logout")

            # Should still return 200 OK (idempotent operation)
            assert response.status_code == status.HTTP_200_OK

    def test_login_with_invalid_provider(self, auth_test_client):
        """Test login initiation with invalid provider parameter."""
        # Assuming the router accepts provider parameter
        response = auth_test_client.get(
            "/auth/web/login?provider=nonexistent-provider", follow_redirects=False
        )

        # Should either use default provider or return error
        # This depends on implementation - adjust based on actual behavior
        assert response.status_code in [302, 400]  # Either redirect or bad request
