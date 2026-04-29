"""Shared types for port forwarding."""

import subprocess
from dataclasses import dataclass, field


class PortForwardError(Exception):
    """Error during port forwarding setup."""


@dataclass
class PortForwardProcess:
    """Tracks an active port forward process with reference counting."""

    process: subprocess.Popen[str]
    ref_count: int = field(default=0, init=False)
