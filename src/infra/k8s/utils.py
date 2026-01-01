"""Utility functions for the Kubernetes infrastructure layer.

Provides helper functions for running async code in sync contexts
and other common utilities.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


def run_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine in a blocking sync context.

    This is useful for calling async KubernetesController methods
    from synchronous CLI commands.

    Args:
        coro: The coroutine to execute

    Returns:
        The result of the coroutine

    Example:
        from src.infra.k8s import KubectlController, run_sync

        controller = KubectlController()
        pods = run_sync(controller.get_pods("my-namespace"))
    """
    try:
        asyncio.get_running_loop()
        # We're inside an async context with a running loop
        # Create a new loop in a thread to avoid blocking
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No running loop, create a new one
        result: T = asyncio.run(coro)
        return result
