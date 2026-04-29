"""Secrets management mixin for Fly.io controller."""

from __future__ import annotations

from .base import FlyCtlBase
from .types import CommandResult


class FlySecretsMixin(FlyCtlBase):
    """Secret operations: set, list, unset."""

    async def secrets_set(
        self,
        app_name: str,
        secrets: dict[str, str],
        *,
        stage: bool = False,
    ) -> CommandResult:
        """Set secrets for a Fly app."""
        args = ["secrets", "set"]
        args.extend([f"{k}={v}" for k, v in secrets.items()])
        args.extend(["-a", app_name])
        if stage:
            args.append("--stage")
        return await self._run_flyctl(args)

    async def secrets_list(self, app_name: str) -> list[str]:
        """List secret names for a Fly app (values are not shown)."""
        result = await self._run_flyctl(["secrets", "list", "-a", app_name])
        if not result.success:
            return []

        lines = result.stdout.strip().split("\n")
        names = []
        for line in lines[1:]:  # Skip header
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                names.append(line.split("|")[0].strip())
            else:
                tokens = line.split()
                if tokens and tokens[0] == "*":
                    tokens = tokens[1:]
                if tokens:
                    names.append(tokens[0])
        return names

    async def secrets_unset(
        self,
        app_name: str,
        names: list[str],
    ) -> CommandResult:
        """Remove secrets from a Fly app."""
        return await self._run_flyctl(["secrets", "unset", *names, "-a", app_name])
