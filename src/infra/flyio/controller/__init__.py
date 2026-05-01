"""Fly.io controller using flyctl CLI commands.

This package provides FlyCtlController for async operations and
FlyCtlControllerSync for synchronous CLI usage.

The controller is composed from domain-specific mixins:
- FlyAuthMixin: Authentication (login, logout, whoami)
- FlyManagedPostgresMixin: Managed Postgres (MPG) operations
- FlyUnmanagedPostgresMixin: Legacy Postgres operations
- FlySecretsMixin: Secrets management
- FlyAppsMixin: App lifecycle and deployment
- FlyMachinesMixin: Machine management, scaling, logs

Example:
    # Async usage
    controller = FlyCtlController()
    if await controller.is_authenticated():
        clusters = await controller.mpg_list()

    # Sync usage (for CLI commands)
    sync_controller = FlyCtlControllerSync()
    clusters = sync_controller.mpg_list()

To regenerate type stubs after modifying this package:
    python -m src.infra.flyio.controller

Internal layout
---------------
- _controller.py  — FlyCtlController + FlyCtlControllerSync definitions
- _stubs.py       — generate_sync_stubs() (used only by __main__.py)
- types.py        — CommandResult and other public dataclasses
- base.py, apps.py, auth.py, …  — mixin modules
"""

from __future__ import annotations

from ._controller import FlyCtlController, FlyCtlControllerSync
from .types import BackupInfo, CommandResult, FlyAppInfo, ManagedPostgresInfo

__all__ = [
    "FlyCtlController",
    "FlyCtlControllerSync",
    "BackupInfo",
    "CommandResult",
    "FlyAppInfo",
    "ManagedPostgresInfo",
]
