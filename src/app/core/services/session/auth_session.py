import secrets
import time

from src.app.core.models.session import AuthSession
from src.app.core.security import (
    sanitize_return_url,
)
from src.app.core.services.storage.session import SessionStorage
from src.app.runtime.context import get_config


class AuthSessionService:
    def __init__(self, session_storage: SessionStorage) -> None:
        self._storage = session_storage

    async def create_auth_session(
        self,
        pkce_verifier: str,
        state: str,
        nonce: str,
        provider: str,
        return_to: str,
        client_fingerprint_hash: str,
    ) -> str:
        """Create secure auth session for OIDC flow.

        Args:
            pkce_verifier: PKCE code verifier
            state: CSRF state parameter
            nonce: OIDC nonce parameter
            provider: OIDC provider identifier
            return_to: Post-auth redirect URI (sanitized)
            client_fingerprint: Client browser fingerprint hash

        Returns:
            Session ID
        """

        # Sanitize return URL for security
        safe_return_to = sanitize_return_url(
            return_to, allowed_hosts=get_config().oidc.allowed_redirect_hosts
        )

        auth_session = AuthSession.create(
            session_id=secrets.token_urlsafe(32),
            pkce_verifier=pkce_verifier,
            state=state,
            nonce=nonce,
            provider=provider,
            return_to=safe_return_to,
            client_fingerprint_hash=client_fingerprint_hash,
            ttl_seconds=600,  # 10 minutes
        )

        await self._storage.set(f"auth:{auth_session.id}", auth_session, 600)
        return auth_session.id

    async def get_auth_session(self, session_id: str) -> AuthSession | None:
        """Get auth session by ID with security validation.

        Args:
            session_id: Session identifier

        Returns:
            Auth session or None if not found/expired/invalid
        """
        auth_session: AuthSession | None = await self._storage.get(
            f"auth:{session_id}", AuthSession
        )

        if not auth_session:
            return None

        # Validate session hasn't been used and isn't expired
        if auth_session.used or auth_session.is_expired():
            await self._storage.delete(f"auth:{session_id}")
            return None

        return auth_session

    async def delete_auth_session(self, session_id: str) -> None:
        """Delete auth session.

        Args:
            session_id: Session identifier
        """
        await self._storage.delete(f"auth:{session_id}")

    async def update_auth_session(
        self,
        session_id: str,
        return_to: str | None = None,
        extension_seconds: int | None = None,
    ) -> AuthSession:
        """Update auth session with new data.

        Args:
            session_id: Session identifier
            return_to: Updated return URL (will be sanitized)
            extension_seconds: Extension time in seconds (can be negative to expire early)

        Returns:
            Updated auth session

        Raises:
            ValueError: If session not found or already used
        """
        auth_session = await self._storage.get(f"auth:{session_id}", AuthSession)

        if not auth_session:
            raise ValueError("Auth session not found")

        if auth_session.used:
            raise ValueError("Auth session already used")

        if auth_session.is_expired():
            await self._storage.delete(f"auth:{session_id}")
            raise ValueError("Auth session expired")

        # Update return URL if provided (with sanitization)
        if return_to is not None:
            safe_return_to = sanitize_return_url(
                return_to, allowed_hosts=get_config().oidc.allowed_redirect_hosts
            )
            auth_session.return_to = safe_return_to

        # Extend/modify session expiry if requested
        if extension_seconds is not None and extension_seconds != 0:
            auth_session.expires_at = int(time.time()) + extension_seconds

        # Check if session is now expired (e.g., from negative extension)
        if auth_session.is_expired():
            await self._storage.delete(f"auth:{auth_session.id}")
            return auth_session  # Return the expired session without storing it

        # Save updated session
        ttl = max(
            1, auth_session.expires_at - int(time.time())
        )  # Ensure ttl is at least 1 second
        await self._storage.set(f"auth:{auth_session.id}", auth_session, ttl)

        return auth_session

    async def list_auth_sessions(self) -> list[AuthSession]:
        """List all active auth sessions.

        Returns:
            List of active auth sessions
        """
        return await self._storage.list_sessions("auth:*", AuthSession)

    async def validate_auth_session(
        self,
        session_id: str,
        state: str | None,
        client_fingerprint_hash: str,
    ) -> AuthSession | None:
        """Validate auth session with security checks.

        Args:
            session_id: Session identifier
            state: State parameter to validate
            client_fingerprint_hash: Client fingerprint to validate

        Returns:
            Valid auth session or None if validation fails
        """
        if not state:
            return None

        auth_session = await self.get_auth_session(session_id)
        if not auth_session:
            return None

        # Validate state parameter (CSRF protection)
        if state != auth_session.state:
            await self.delete_auth_session(session_id)
            return None
        # Validate client fingerprint (session hijacking protection)
        if client_fingerprint_hash != auth_session.client_fingerprint_hash:
            await self.delete_auth_session(session_id)
            return None

        return auth_session

    async def mark_auth_session_used(self, session_id: str) -> None:
        """Mark auth session as used to prevent replay attacks.

        Args:
            session_id: Session identifier
        """
        auth_session = await self._storage.get(f"auth:{session_id}", AuthSession)

        if auth_session:
            auth_session.mark_used()
            await self._storage.set(f"auth:{auth_session.id}", auth_session, 600)

    async def purge_expired(self) -> None:
        """Cleanup expired sessions from storage."""
        await self._storage.cleanup_expired()
