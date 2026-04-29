"""Fly Kubernetes Service (FKS) mixin for Fly.io controller."""

from __future__ import annotations

from typing import Any

from .base import FlyCtlBase
from .types import CommandResult


class FlyFksMixin(FlyCtlBase):
    """FKS operations: create, list, destroy, save-kubeconfig."""

    async def fks_create(
        self,
        name: str,
        region: str,
        *,
        org: str | None = None,
        kubeconfig_output: str | None = None,
    ) -> CommandResult:
        """Create a Fly Kubernetes Service (FKS) cluster."""
        args = [
            "extensions",
            "kubernetes",
            "create",
            "--name",
            name,
            "--region",
            region,
        ]
        if org:
            args.extend(["--org", org])
        if kubeconfig_output:
            args.extend(["--output", kubeconfig_output])
        return await self._run_flyctl(args, timeout=300)

    async def fks_list(self) -> list[dict[str, Any]]:
        """List FKS clusters."""
        success, data = await self._run_flyctl_json(
            ["extensions", "kubernetes", "list"]
        )
        if success and isinstance(data, list):
            return data
        return []

    async def fks_destroy(
        self,
        cluster_name: str,
        *,
        confirm: bool = False,
    ) -> CommandResult:
        """Destroy an FKS cluster."""
        args = ["extensions", "kubernetes", "destroy", cluster_name]
        if confirm:
            args.append("--yes")
        return await self._run_flyctl(args, timeout=300)

    async def fks_save_kubeconfig(
        self,
        cluster_name: str,
        *,
        output: str | None = None,
    ) -> CommandResult:
        """Save the kubeconfig for an FKS cluster."""
        args = ["extensions", "kubernetes", "save-kubeconfig", cluster_name]
        if output:
            args.extend(["--output", output])
        return await self._run_flyctl(args)
