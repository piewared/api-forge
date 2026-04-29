"""Apps and deployment mixin for Fly.io controller."""

from __future__ import annotations

from typing import Any

from .base import FlyCtlBase
from .types import CommandResult, FlyAppInfo, parse_app_info


class FlyAppsMixin(FlyCtlBase):
    """App management: create, destroy, deploy, status, info, list, regions."""

    async def apps_list(self, *, org: str | None = None) -> list[FlyAppInfo]:
        """List Fly apps."""
        args = ["apps", "list"]
        if org:
            args.extend(["--org", org])

        success, data = await self._run_flyctl_json(args)
        if not success or not isinstance(data, list):
            return []

        return [parse_app_info(item) for item in data]

    async def app_info(self, app_name: str) -> FlyAppInfo | None:
        """Get info about a specific app."""
        success, data = await self._run_flyctl_json(["status", "--app", app_name])
        if not success or not isinstance(data, dict):
            return None

        return FlyAppInfo(
            name=data.get("Name", app_name),
            organization=data.get("Organization", {}).get("Slug", ""),
            status=data.get("Status", "unknown"),
            hostname=data.get("Hostname", f"{app_name}.fly.dev"),
        )

    async def regions_list(self) -> list[dict[str, Any]]:
        """List available Fly.io regions."""
        success, data = await self._run_flyctl_json(["platform", "regions"])
        if success and isinstance(data, list):
            return data
        return []

    async def app_create(
        self,
        name: str,
        *,
        org: str | None = None,
        generate_name: bool = False,
    ) -> CommandResult:
        """Create a new Fly.io app."""
        args = ["apps", "create"]
        if generate_name:
            args.append("--generate-name")
        else:
            args.append(name)
        if org:
            args.extend(["--org", org])
        return await self._run_flyctl(args)

    async def app_destroy(
        self,
        app_name: str,
        *,
        confirm: bool = False,
    ) -> CommandResult:
        """Destroy a Fly.io app."""
        args = ["apps", "destroy", app_name]
        if confirm:
            args.append("--yes")
        return await self._run_flyctl(args)

    async def deploy(
        self,
        *,
        app: str | None = None,
        config: str | None = None,
        dockerfile: str | None = None,
        image: str | None = None,
        primary_region: str | None = None,
        strategy: str | None = None,
        wait_timeout: int | None = None,
        no_cache: bool = False,
        build_only: bool = False,
        cwd: str | None = None,
    ) -> CommandResult:
        """Deploy an app to Fly.io."""
        args = ["deploy"]
        if app:
            args.extend(["--app", app])
        if config:
            args.extend(["--config", config])
        if dockerfile:
            args.extend(["--dockerfile", dockerfile])
        if image:
            args.extend(["--image", image])
        if primary_region:
            args.extend(["--primary-region", primary_region])
        if strategy:
            args.extend(["--strategy", strategy])
        if wait_timeout:
            args.extend(["--wait-timeout", str(wait_timeout)])
        if no_cache:
            args.append("--no-cache")
        if build_only:
            args.append("--build-only")
        return await self._run_flyctl(args, timeout=600, cwd=cwd)

    async def app_status(
        self,
        app_name: str,
    ) -> dict[str, Any] | None:
        """Get detailed status of a Fly.io app."""
        success, data = await self._run_flyctl_json(["status", "--app", app_name])
        if success and isinstance(data, dict):
            return data
        return None
