"""Docker Compose command helpers."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path


class ComposeRunner:
    """Wrapper for Docker Compose commands with consistent defaults."""

    def __init__(
        self,
        project_root: Path,
        *,
        compose_file: Path,
        project_name: str | None = None,
    ) -> None:
        self._project_root = project_root
        self._compose_file = compose_file
        self._project_name = project_name

    def _base_cmd(self) -> list[str]:
        cmd = ["docker", "compose"]
        if self._project_name:
            cmd.extend(["-p", self._project_name])
        cmd.extend(["-f", str(self._compose_file)])
        return cmd

    def run(
        self,
        args: Sequence[str],
        *,
        capture_output: bool = False,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        cmd = self._base_cmd() + list(args)
        return subprocess.run(
            cmd,
            cwd=self._project_root,
            capture_output=capture_output,
            text=True,
            check=check,
        )

    def logs(
        self,
        *,
        service: str | None = None,
        follow: bool = False,
        tail: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        args = ["logs"]
        if tail is not None:
            args.append(f"--tail={tail}")
        if follow:
            args.append("--follow")
        if service:
            args.append(service)
        return self.run(args, check=True)

    def restart(
        self, *, service: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        args = ["restart"]
        if service:
            args.append(service)
        return self.run(args, check=True)

    def build(
        self, *, service: str | None = None, no_cache: bool = False
    ) -> subprocess.CompletedProcess[str]:
        args = ["build"]
        if no_cache:
            args.append("--no-cache")
        if service:
            args.append(service)
        return self.run(args, check=True)
