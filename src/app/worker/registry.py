# worker/registry.py
"""
Temporal Worker Registry System.

This module provides a centralized registry for Temporal workflows and activities,
enabling automatic discovery, task queue management, and worker lifecycle control.

Key Features:
    - Decorator-based registration of workflows and activities
    - Automatic module discovery and registration


Usage:
    # Register workflows and activities with decorators
    @workflow_defn(queue="orders")
    @workflow.defn
    class OrderWorkflow:
        ...

    @activity_defn(queue="orders")
    @activity.defn
    async def process_payment(...):
        ...

"""

import importlib
import pkgutil
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, cast

# from loguru import logger
from temporalio import activity, workflow

from src.app.worker.workflows.base import BaseWorkflow


def discover(module_path: str) -> list[Any]:
    """
    Discover all registered Temporal components in a module.

    Recursively imports all modules in the given package and returns items
    that have been marked with __temporal_registered__ = True.

    Args:
        module_path: Fully qualified module path (e.g., "src.app.worker.activities")

    Returns:
        List of registered workflow classes and activity functions
    """
    pkg = importlib.import_module(module_path)
    items = []
    for m in pkgutil.iter_modules(pkg.__path__, prefix=f"{module_path}."):
        mod = importlib.import_module(m.name)
        items += [getattr(mod, n) for n in dir(mod)]
    return [i for i in items if getattr(i, "__temporal_registered__", False)]


# central registry: queue -> list[callable]
_ACTIVITY_BY_QUEUE: dict[str, set[Callable[..., Any]]] = {}
_WORKFLOW_BY_QUEUE: dict[str, set[type]] = {}


P = ParamSpec("P")
R = TypeVar("R")


def activity_defn(
    *, queue: str, **activity_kwargs: Any
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator for registering Temporal activities to a task queue.

    This decorator wraps Temporal's @activity.defn and adds automatic
    registration to the global registry for the specified queue.

    Keeps the original function's signature for type checkers.

    Args:
        queue: Task queue name where this activity will be registered
        **activity_kwargs: Additional arguments passed to @activity.defn
                          (e.g., name, dynamic, namespace)

    Returns:
        Decorated activity function with queue metadata

    Example:
        @activity_defn(queue="payments", name="charge-card")
        @activity.defn
        async def charge_card(order_id: str, amount: int) -> str:
            ...

    Raises:
        ValueError: If queue is not provided
    """

    if not queue:
        raise ValueError("activity_defn requires 'queue'")

    def deco(fn: Callable[P, R]) -> Callable[P, R]:
        # Apply Temporal's decorator (already typed with ParamSpec/TypeVar)
        wrapped = activity.defn(**activity_kwargs)(fn)
        # Attach metadata / register (your registries etc.)
        wrapped.__temporal_registered__ = True
        wrapped.__activity_queue__ = queue
        _ACTIVITY_BY_QUEUE.setdefault(queue, set()).add(wrapped)
        # logger.debug(f"Registering activity {wrapped.__name__} to queue '{queue}'")
        # Tell the checker: same signature as input
        return cast(Callable[P, R], wrapped)

    return deco


WFClass = TypeVar("WFClass", bound="type[BaseWorkflow[Any, Any]]")


def workflow_defn(
    *, queue: str, **workflow_kwargs: Any
) -> Callable[[WFClass], WFClass]:
    """
    Decorator for registering Temporal workflows to a task queue.

    This decorator wraps Temporal's @workflow.defn and adds automatic
    registration to the global registry for the specified queue.

    Args:
        queue: Task queue name where this workflow will be registered
        **workflow_kwargs: Additional arguments passed to @workflow.defn
                          (e.g., name, dynamic, sandboxed)

    Returns:
        Decorated workflow class with queue metadata

    Example:
        @workflow_defn(queue="orders")
        @workflow.defn
        class OrderWorkflow:
            @workflow.run
            async def run(self, order_id: str) -> dict:
                ...

    Raises:
        ValueError: If queue is not provided
    """
    # logger.debug("Registering workflow")
    if not queue:
        raise ValueError("workflow_defn requires 'queue'")

    def deco(cls: WFClass) -> WFClass:
        wrapped_cls = workflow.defn(**workflow_kwargs)(cls)
        # attach metadata + register
        wrapped_cls.__temporal_registered__ = True
        wrapped_cls.__workflow_queue__ = queue
        # logger.debug(f"Registering workflow {wrapped_cls.__name__} to queue '{queue}'")
        _WORKFLOW_BY_QUEUE.setdefault(queue, set()).add(wrapped_cls)
        # Tell the checker: this decorator preserves the original class type
        return cast(WFClass, wrapped_cls)

    return deco


def autodiscover_modules(packages: list[str] | None = None) -> None:
    """
    Automatically discover and import all modules in specified packages.

    This triggers registration of all decorated workflows and activities
    by importing their modules. Must be called before creating workers.

    Args:
        packages: List of package paths to scan. Defaults to:
                 ["src.app.worker.activities", "src.app.worker.workflows"]

    Note:
        This function uses pkgutil.walk_packages to recursively import
        all submodules. Any @workflow_defn or @activity_defn decorators
        will execute during import, registering their handlers.
    """
    for mod_path in packages or [
        "src.app.worker.activities",
        "src.app.worker.workflows",
    ]:
        pkg = importlib.import_module(mod_path)
        for m in pkgutil.walk_packages(pkg.__path__, prefix=f"{mod_path}."):
            importlib.import_module(m.name)


def get_activities_by_queue() -> dict[str, set[Callable[..., Any]]]:
    """Get the registered activities organized by task queue.

    Returns:
        Dictionary mapping task queue names to sets of activity callables.
    """
    return _ACTIVITY_BY_QUEUE.copy()  # copy to prevent external mutation


def get_workflows_by_queue() -> dict[str, set[type]]:
    """Get the registered workflows organized by task queue.

    Returns:
        Dictionary mapping task queue names to sets of workflow classes.
    """
    return _WORKFLOW_BY_QUEUE.copy()  # copy to prevent external mutation
