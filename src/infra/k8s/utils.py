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
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, create a new one
        return asyncio.run(coro)
    else:
        # We're inside an async context, use run_until_complete
        # This handles nested async calls
        if loop.is_running():
            # Create a new loop in a thread to avoid blocking
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
