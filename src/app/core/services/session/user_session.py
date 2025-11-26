import secrets
import time
from typing import TYPE_CHECKING

from src.app.core.models.session import UserSession
from src.app.core.security import (
    hash_client_fingerprint,
)
from src.app.core.services.storage.session import SessionStorage
from src.app.runtime.context import get_config

if TYPE_CHECKING:
    from src.app.core.services.oidc_client_service import OidcClientService


class UserSessionService:
    """Service for managing user sessions."""

    def __init__(self, session_storage: SessionStorage) -> None:
        self._storage = session_storage

    async def create_user_session(
        self,
        user_id: str,
        provider: str,
        client_fingerprint: str,
        refresh_token: str | None = None,
        access_token: str | None = None,
        access_token_expires_at: int | None = None,
    ) -> str:
        """Create secure user session.

        Args:
            user_id: Internal user ID
            provider: OIDC provider identifier
            client_fingerprint: Client browser fingerprint
            refresh_token: OAuth refresh token
            access_token: OAuth access token
            access_token_expires_at: Access token expiry timestamp

        Returns:
            Session ID
        """
        storage = self._storage
        main_config = get_config()

        user_session = UserSession.create(
            session_id=secrets.token_urlsafe(32),
            user_id=user_id,
            provider=provider,
            client_fingerprint=hash_client_fingerprint(client_fingerprint),
            session_max_age=main_config.app.session_max_age,
        )

        # Set token information if provided
        if access_token:
            user_session.update_tokens(
                access_token=access_token,
                refresh_token=refresh_token,
                access_token_expires_at=access_token_expires_at,
            )

        await storage.set(
            f"user:{user_session.id}", user_session, main_config.app.session_max_age
        )
        return user_session.id

    async def get_user_session(self, session_id: str) -> UserSession | None:
        """Get user session by ID with security validation.

        Args:
            session_id: Session identifier

        Returns:
            User session or None if not found/expired
        """
        storage = self._storage
        user_session = await storage.get(f"user:{session_id}", UserSession)

        if not user_session:
            return None

        # Check expiry
        if user_session.is_expired():
            await storage.delete(f"user:{session_id}")
            return None

        # Update last accessed time
        user_session.update_access()
        await storage.set(
            f"user:{user_session.id}", user_session, get_config().app.session_max_age
        )

        return user_session

    async def validate_user_session(
        self,
        session_id: str,
        client_fingerprint: str,
    ) -> UserSession | None:
        """Validate user session with security checks.

        Args:
            session_id: Session identifier
            client_fingerprint: Client fingerprint to validate

        Returns:
            Valid user session or None if validation fails
        """
        user_session = await self.get_user_session(session_id)
        if not user_session:
            return None

        # Validate client fingerprint (session hijacking protection)
        expected_hash = hash_client_fingerprint(client_fingerprint)
        if expected_hash != user_session.client_fingerprint:
            await self.delete_user_session(session_id)
            return None

        return user_session

    async def rotate_user_session(self, session_id: str) -> str:
        """Rotate user session ID for security.

        Args:
            session_id: Current session identifier

        Returns:
            New session ID

        Raises:
            ValueError: If session not found
        """
        storage = self._storage
        user_session = await storage.get(f"user:{session_id}", UserSession)

        if not user_session:
            raise ValueError("Session not found")

        # Generate new session ID
        new_session_id = secrets.token_urlsafe(32)
        user_session.rotate_session_id(new_session_id)

        # Store with new ID and remove old
        await storage.set(
            f"user:{user_session.id}", user_session, get_config().app.session_max_age
        )
        await storage.delete(f"user:{session_id}")

        return new_session_id

    async def delete_user_session(self, session_id: str) -> None:
        """Delete user session.

        Args:
            session_id: Session identifier
        """
        await self._storage.delete(f"user:{session_id}")

    async def refresh_user_session(
        self, session_id: str, oidc_client: "OidcClientService"
    ) -> str:
        """Refresh user session using stored refresh token.

        Args:
            session_id: Current session identifier

        Returns:
            New session ID

        Raises:
            ValueError: If session not found or refresh fails
        """
        config = get_config()
        policy = config.oidc.refresh_tokens
        if not policy.enabled:
            raise ValueError("Refresh tokens are disabled")

        user_session = await self.get_user_session(session_id)
        if not user_session:
            raise ValueError("Session not found or expired")

        if not user_session.refresh_token:
            raise ValueError("No refresh token available")

        if (
            policy.max_session_lifetime_seconds
            and int(time.time()) - user_session.created_at
            > policy.max_session_lifetime_seconds
        ):
            raise ValueError("Refresh token lifetime exceeded")

        try:
            # Refresh tokens with provider
            tokens = await oidc_client.refresh_access_token(
                user_session.refresh_token, user_session.provider
            )

            # Update session with refreshed tokens
            user_session.update_tokens(
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token or user_session.refresh_token,
                access_token_expires_at=tokens.expires_at,
            )

            # Save the updated session with new tokens first
            storage = self._storage
            await storage.set(
                f"user:{user_session.id}",
                user_session,
                config.app.session_max_age,
            )

            # Then rotate session ID for added security
            new_session_id = await self.rotate_user_session(session_id)
            return new_session_id

        except Exception as e:
            # Delete invalid session
            await self.delete_user_session(session_id)
            raise ValueError(f"Token refresh failed: {str(e)}") from e

    async def update_user_session(
        self,
        session_id: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        access_token_expires_at: int | None = None,
        client_fingerprint: str | None = None,
        extension_seconds: int | None = None,
    ) -> UserSession:
        """Update user session with new data.

        Args:
            session_id: Session identifier
            access_token: New access token (optional)
            refresh_token: New refresh token (optional)
            access_token_expires_at: New access token expiry (optional)
            client_fingerprint: Updated client fingerprint (optional)
            extension_seconds: Custom extension time (defaults to session_max_age if extend_session=True)

        Returns:
            Updated user session

        Raises:
            ValueError: If session not found
        """
        storage = self._storage
        user_session = await storage.get(f"user:{session_id}", UserSession)

        if not user_session:
            raise ValueError("Session not found")

        # Update tokens if provided
        if (
            access_token is not None
            or refresh_token is not None
            or access_token_expires_at is not None
        ):
            user_session.update_tokens(
                access_token=access_token,
                refresh_token=refresh_token,
                access_token_expires_at=access_token_expires_at,
            )

        # Update client fingerprint if provided (re-hash for security)
        if client_fingerprint is not None:
            user_session.client_fingerprint = hash_client_fingerprint(
                client_fingerprint
            )

        # Update access time
        user_session.update_access()

        # Extend session expiry if requested
        if extension_seconds is not None:
            extension_time = extension_seconds or get_config().app.session_max_age
            user_session.expires_at = int(time.time()) + extension_time

        # Check if session is now expired (e.g., from negative extension)
        if user_session.is_expired():
            await storage.delete(f"user:{user_session.id}")
            return user_session  # Return the expired session without storing it

        # Save updated session
        ttl = max(
            1, user_session.expires_at - int(time.time())
        )  # Ensure ttl is at least 1 second
        await storage.set(f"user:{user_session.id}", user_session, ttl)

        return user_session

    async def extend_user_session(
        self, session_id: str, additional_seconds: int | None = None
    ) -> UserSession:
        """Extend user session expiry time.

        Args:
            session_id: Session identifier
            additional_seconds: Additional seconds to extend (defaults to session_max_age)

        Returns:
            Updated user session

        Raises:
            ValueError: If session not found
        """
        return await self.update_user_session(
            session_id=session_id, extension_seconds=additional_seconds
        )

    async def list_user_sessions(self, user_id: str | None = None) -> list[UserSession]:
        """List active user sessions, optionally filtered by user ID.

        Args:
            user_id: Optional user ID to filter sessions by

        Returns:
            List of active user sessions
        """
        sessions = await self._storage.list_sessions("user:*", UserSession)

        # Filter by user_id if provided
        if user_id is not None:
            sessions = [s for s in sessions if s.user_id == user_id]

        return sessions

    async def purge_expired(self) -> None:
        """Cleanup expired sessions from storage."""
        await self._storage.cleanup_expired()
