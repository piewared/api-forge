"""Session management utilities for counting, cleaning, and clearing sessions."""

from src.app.core.models.session import AuthSession, UserSession
from src.app.core.services.session.auth_session import AuthSessionService
from src.app.core.services.session.user_session import UserSessionService
from src.app.core.services.storage.session import SessionStorage


async def count_active_sessions(
    user_session_service: UserSessionService, auth_session_service: AuthSessionService
) -> dict[str, int]:
    """Count active auth and user sessions.

    Returns:
        Dictionary with 'auth' and 'user' session counts
    """
    auth_sessions = await auth_session_service.list_auth_sessions()
    user_sessions = await user_session_service.list_user_sessions()

    return {"auth": len(auth_sessions), "user": len(user_sessions)}


async def cleanup_expired_sessions(storage: SessionStorage) -> dict[str, int]:
    """Clean up expired sessions and return counts.

    Returns:
        Dictionary with cleanup counts for auth and user sessions
    """
    counts = {"auth": 0, "user": 0}

    # Use storage's built-in cleanup if available
    await storage.cleanup_expired()

    # Get lists of all sessions and check expiry
    try:
        auth_keys = await storage.list_keys("auth:*")
        for key in auth_keys:
            try:
                auth_session = await storage.get(key, AuthSession)
                if not auth_session or auth_session.is_expired():
                    await storage.delete(key)
                    counts["auth"] += 1
            except Exception:
                # Delete corrupted sessions
                await storage.delete(key)
                counts["auth"] += 1

        user_keys = await storage.list_keys("user:*")
        for key in user_keys:
            try:
                user_session = await storage.get(key, UserSession)
                if not user_session or user_session.is_expired():
                    await storage.delete(key)
                    counts["user"] += 1
            except Exception:
                # Delete corrupted sessions
                await storage.delete(key)
                counts["user"] += 1
    except Exception:
        # Fall back to storage cleanup count
        pass

    return counts


async def clear_all_sessions(storage: SessionStorage) -> dict[str, int]:
    """Clear all auth and user sessions (admin/testing function).

    WARNING: This will log out all users and invalidate all auth sessions.
    Use with caution, typically only for testing or emergency situations.

    Returns:
        Dictionary with counts of cleared sessions
    """
    counts = {"auth": 0, "user": 0}

    try:
        # Clear auth sessions
        auth_keys = await storage.list_keys("auth:*")
        for key in auth_keys:
            await storage.delete(key)
            counts["auth"] += 1

        # Clear user sessions
        user_keys = await storage.list_keys("user:*")
        for key in user_keys:
            await storage.delete(key)
            counts["user"] += 1
    except Exception:
        # Fall back gracefully
        pass

    return counts
