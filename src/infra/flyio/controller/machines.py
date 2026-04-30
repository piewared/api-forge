"""Machines, scaling, and logs mixin for Fly.io controller."""

from __future__ import annotations

from typing import Any

from .base import FlyCtlBase
from .types import CommandResult


class FlyMachinesMixin(FlyCtlBase):
    """Machine and scaling operations: list, stop, start, destroy, run, scale, logs."""

    async def scale_count(
        self,
        app_name: str,
        count: int,
        *,
        region: str | None = None,
    ) -> CommandResult:
        """Scale the number of machines for an app."""
        args = ["scale", "count", str(count), "--app", app_name]
        if region:
            args.extend(["--region", region])
        args.append("--yes")
        return await self._run_flyctl(args)

    async def scale_vm(
        self,
        app_name: str,
        vm_size: str,
    ) -> CommandResult:
        """Scale the VM size for an app."""
        args = ["scale", "vm", vm_size, "--app", app_name]
        return await self._run_flyctl(args)

    async def scale_memory(
        self,
        app_name: str,
        memory_mb: int,
    ) -> CommandResult:
        """Scale the memory for an app's VMs."""
        args = ["scale", "memory", str(memory_mb), "--app", app_name]
        return await self._run_flyctl(args)

    async def logs(
        self,
        app_name: str,
        *,
        region: str | None = None,
        instance: str | None = None,
    ) -> CommandResult:
        """Get logs from a Fly.io app."""
        args = ["logs", "--app", app_name, "--no-tail"]
        if region:
            args.extend(["--region", region])
        if instance:
            args.extend(["--instance", instance])
        return await self._run_flyctl(args, timeout=30)

    async def machines_list(
        self,
        app_name: str,
    ) -> list[dict[str, Any]]:
        """List machines for a Fly.io app."""
        success, data = await self._run_flyctl_json(
            ["machines", "list", "--app", app_name]
        )
        if success and isinstance(data, list):
            return data
        return []

    async def machine_stop(
        self,
        app_name: str,
        machine_id: str,
    ) -> CommandResult:
        """Stop a specific machine."""
        return await self._run_flyctl(
            ["machines", "stop", machine_id, "--app", app_name]
        )

    async def machine_start(
        self,
        app_name: str,
        machine_id: str,
    ) -> CommandResult:
        """Start a specific machine."""
        return await self._run_flyctl(
            ["machines", "start", machine_id, "--app", app_name]
        )

    async def machine_destroy(
        self,
        app_name: str,
        machine_id: str,
        *,
        force: bool = False,
    ) -> CommandResult:
        """Destroy a specific machine."""
        args = ["machines", "destroy", machine_id, "--app", app_name]
        if force:
            args.append("--force")
        return await self._run_flyctl(args)

    async def machine_run(
        self,
        image: str,
        *,
        app_name: str,
        command: list[str] | None = None,
        entrypoint: str | None = None,
        env: dict[str, str] | None = None,
        region: str | None = None,
        rm: bool = True,
        timeout: int | None = 600,
        capture_output: bool = False,
    ) -> CommandResult:
        """Run a one-shot machine and (optionally) auto-remove it when done.

        Note on timeouts: ``fly machine run`` does **not** expose a flag to
        extend its internal "wait for machine to reach ``started``" budget
        (hardcoded at 5 minutes). The ``timeout`` argument here is just the
        outer subprocess kill. Cold pulls of large images can blow past
        flyctl's hard 5 min wait; callers handle that via retry rather than
        a longer wait — see ``run_temporal_schema_setup``.

        Args:
            capture_output: If True, capture stdout/stderr into CommandResult
                instead of streaming them to the terminal.  Set True for
                one-shot init jobs so their output appears in error messages;
                leave False for interactive/long-running deployments where
                real-time streaming is preferred.
        """
        args = ["machine", "run", image, "--app", app_name]
        if rm:
            args.append("--rm")
        if region:
            args.extend(["--region", region])
        if entrypoint:
            args.extend(["--entrypoint", entrypoint])
        for key, value in (env or {}).items():
            args.extend(["--env", f"{key}={value}"])
        if command:
            args.append("--")
            args.extend(command)
        return await self._run_flyctl(
            args, capture_output=capture_output, timeout=timeout
        )
