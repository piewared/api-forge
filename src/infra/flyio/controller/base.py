"""Base class with low-level flyctl command execution."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from typing import Any

from .types import CommandResult

# Environment variables we layer on top of the inherited process env when
# invoking flyctl. ``FLY_NO_UPDATE_CHECK=1`` suppresses flyctl's in-process
# self-update — the auto-upgrade fires mid-deploy when an outdated flyctl is
# present, adds ~30 s, and emits a curl progress bar that interleaves with
# our own status output. Users still upgrade flyctl on their own schedule.
_FLYCTL_ENV_OVERRIDES = {"FLY_NO_UPDATE_CHECK": "1"}


class FlyCtlBase:
    """Base class providing flyctl CLI execution primitives.

    All domain mixins inherit from this class to access _run_flyctl
    and _run_flyctl_json for running flyctl commands.
    """

    async def _run_flyctl(
        self,
        args: list[str],
        *,
        capture_output: bool = True,
        input_data: str | None = None,
        timeout: int | None = None,
        cwd: str | None = None,
    ) -> CommandResult:
        """Run a flyctl command asynchronously.

        Args:
            args: Command arguments (without 'fly' prefix)
            capture_output: Whether to capture stdout/stderr
            input_data: Optional input to send to stdin
            timeout: Command timeout in seconds (None for no timeout)
            cwd: Working directory for the subprocess (defaults to process CWD)

        Returns:
            CommandResult with execution results
        """
        cmd = ["fly", *args]
        env = {**os.environ, **_FLYCTL_ENV_OVERRIDES}

        def _run() -> CommandResult:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=capture_output,
                    text=True,
                    input=input_data,
                    timeout=timeout,
                    cwd=cwd,
                    env=env,
                )
                return CommandResult(
                    success=result.returncode == 0,
                    stdout=result.stdout or "",
                    stderr=result.stderr or "",
                    returncode=result.returncode,
                )
            except subprocess.TimeoutExpired:
                return CommandResult(
                    success=False,
                    stderr=f"Command timed out after {timeout}s",
                    returncode=-1,
                )
            except FileNotFoundError:
                return CommandResult(
                    success=False,
                    stderr="flyctl not found. Install from https://fly.io/docs/flyctl/install/",
                    returncode=-1,
                )

        return await asyncio.to_thread(_run)

    async def _run_flyctl_json(
        self,
        args: list[str],
        *,
        timeout: int | None = None,
    ) -> tuple[bool, dict[str, Any] | list[Any] | None]:
        """Run a flyctl command and parse JSON output.

        Args:
            args: Command arguments (--json flag added automatically)
            timeout: Command timeout in seconds

        Returns:
            Tuple of (success, parsed_json_or_none)
        """
        result = await self._run_flyctl([*args, "--json"], timeout=timeout)
        if result.success and result.stdout:
            try:
                return True, json.loads(result.stdout)
            except json.JSONDecodeError:
                return False, None
        return False, None

    async def is_installed(self) -> bool:
        """Check if the ``fly`` CLI is on PATH.

        Only ``fly`` is checked here: ``_run_flyctl`` invokes ``["fly", ...]``,
        so accepting a ``flyctl``-only system would let this check pass and
        every subsequent command fail with FileNotFoundError.
        """
        return shutil.which("fly") is not None
