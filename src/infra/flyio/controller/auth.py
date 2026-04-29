"""Authentication mixin for Fly.io controller."""

from __future__ import annotations

from .base import FlyCtlBase
from .types import CommandResult


class FlyAuthMixin(FlyCtlBase):
    """Authentication operations: login, logout, whoami, token."""

    async def auth_login(self, *, interactive: bool = False) -> CommandResult:
        """Log in to Fly.io.

        Args:
            interactive: Use email/password instead of browser-based login
        """
        args = ["auth", "login"]
        if interactive:
            args.append("--interactive")
        return await self._run_flyctl(args)

    async def auth_logout(self) -> CommandResult:
        """Log out from Fly.io."""
        return await self._run_flyctl(["auth", "logout"])

    async def auth_whoami(self) -> tuple[bool, str]:
        """Get current authenticated user.

        Returns:
            Tuple of (is_authenticated, email_or_error_message)
        """
        result = await self._run_flyctl(["auth", "whoami"])
        if result.success:
            return True, result.stdout.strip()
        return False, result.stderr.strip()

    async def is_authenticated(self) -> bool:
        """Check if user is authenticated."""
        success, _ = await self.auth_whoami()
        return success

    async def auth_token(self) -> tuple[bool, str]:
        """Get the current auth token.

        Returns:
            Tuple of (success, token_or_error_message)
        """
        result = await self._run_flyctl(["auth", "token"])
        if result.success:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
