"""FlyCtlController and FlyCtlControllerSync class definitions."""

from __future__ import annotations

import inspect
from typing import Any

from src.utils.run_sync import run_sync

from .apps import FlyAppsMixin
from .auth import FlyAuthMixin
from .machines import FlyMachinesMixin
from .managed_postgres import FlyManagedPostgresMixin
from .secrets import FlySecretsMixin
from .unmanaged_postgres import FlyUnmanagedPostgresMixin


class FlyCtlController(
    FlyAuthMixin,
    FlyManagedPostgresMixin,
    FlyUnmanagedPostgresMixin,
    FlySecretsMixin,
    FlyAppsMixin,
    FlyMachinesMixin,
):
    """Controller for Fly.io operations via flyctl CLI.

    Composed from domain-specific mixins, each providing a focused set
    of operations. All methods are async.

    Example:
        controller = FlyCtlController()
        if await controller.is_authenticated():
            clusters = await controller.mpg_list()
            for cluster in clusters:
                print(f"{cluster.name} ({cluster.region}): {cluster.status}")
    """


class FlyCtlControllerSync:
    """Synchronous wrapper for FlyCtlController.

    Automatically wraps all async methods from the underlying controller
    and exposes them as synchronous methods using run_sync(). Wrappers are
    cached on the instance after first access so the inspect/wrapper-build
    cost is paid once per attribute, not per call.

    Type hints are provided via the auto-generated ``__init__.pyi`` stub.
    Regenerate stubs after modifying FlyCtlController:
        python -m src.infra.flyio.controller
    """

    def __init__(self, controller: FlyCtlController | None = None):
        self._controller = controller or FlyCtlController()
        self._sync_cache: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        """Dynamically wrap async methods as sync (with caching)."""
        # __getattr__ is only invoked when normal attribute lookup fails, so
        # _sync_cache and _controller (set in __init__) won't recurse here.
        cache = self.__dict__.get("_sync_cache")
        if cache is not None and name in cache:
            return cache[name]

        attr = getattr(self._controller, name)

        if (
            callable(attr)
            and hasattr(attr, "__code__")
            and inspect.iscoroutinefunction(attr)
        ):

            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                return run_sync(attr(*args, **kwargs))

            if cache is not None:
                cache[name] = sync_wrapper
            return sync_wrapper

        return attr
