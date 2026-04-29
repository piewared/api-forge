"""Unmanaged (legacy) Postgres mixin for Fly.io controller."""

from __future__ import annotations

from .base import FlyCtlBase
from .types import CommandResult, FlyAppInfo, parse_app_info


class FlyUnmanagedPostgresMixin(FlyCtlBase):
    """Legacy Fly Postgres operations: create, list, connect, attach, get password."""

    async def postgres_create(
        self,
        name: str,
        region: str,
        *,
        org: str | None = None,
        volume_size: int | None = None,
        initial_cluster_size: int | None = None,
        vm_cpus: int | None = None,
        vm_cpu_kind: str | None = None,
        vm_memory: int | None = None,
        password: str | None = None,
    ) -> CommandResult:
        """Create an unmanaged Fly Postgres cluster."""
        args = ["postgres", "create", "--name", name, "--region", region]
        if org:
            args.extend(["--org", org])
        if volume_size:
            args.extend(["--volume-size", str(volume_size)])
        if initial_cluster_size:
            args.extend(["--initial-cluster-size", str(initial_cluster_size)])
        if vm_cpus:
            args.extend(["--vm-cpus", str(vm_cpus)])
        if vm_cpu_kind:
            args.extend(["--vm-cpu-kind", vm_cpu_kind])
        if vm_memory:
            args.extend(["--vm-memory", str(vm_memory)])
        if password:
            args.extend(["--password", password])
        return await self._run_flyctl(args)

    async def postgres_list(self) -> list[FlyAppInfo]:
        """List unmanaged Postgres clusters."""
        success, data = await self._run_flyctl_json(["postgres", "list"])
        if not success or not isinstance(data, list):
            return []

        return [parse_app_info(item) for item in data]

    async def postgres_connect(self, app_name: str) -> CommandResult:
        """Connect to unmanaged Postgres cluster (interactive)."""
        return await self._run_flyctl(
            ["postgres", "connect", "-a", app_name], capture_output=False
        )

    async def postgres_attach(
        self,
        postgres_app: str,
        app_name: str,
    ) -> CommandResult:
        """Attach an app to unmanaged Postgres."""
        return await self._run_flyctl(
            ["postgres", "attach", postgres_app, "-a", app_name]
        )

    async def postgres_get_superuser_password(self, app_name: str) -> tuple[bool, str]:
        """Retrieve the superuser password from an unmanaged Fly Postgres app.

        Uses SSH to read the OPERATOR_PASSWORD environment variable from the running VM.
        """
        result = await self._run_flyctl(
            ["ssh", "console", "-a", app_name, "-C", "printenv OPERATOR_PASSWORD"]
        )
        if result.success and result.stdout.strip():
            return True, result.stdout.strip()
        return False, result.stderr.strip() or "Failed to retrieve password"
