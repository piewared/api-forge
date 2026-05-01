"""Run-async-in-sync helper used by both the k8s and flyio infra layers.

Lives under ``src/utils/`` (not ``src/infra/k8s/`` where it began) so that
the ``infra.flyio`` package can import it without dragging in ``infra.k8s``.
This matters when the template is generated with ``include_k8s_deploy=false``
— ``infra/k8s/`` is excluded from the project, but ``infra/flyio/`` is still
expected to import its async-bridge utility from somewhere.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


def run_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine in a blocking sync context.

    Useful for calling async controller methods from synchronous CLI
    commands.

    Args:
        coro: The coroutine to execute

    Returns:
        The result of the coroutine
    """
    try:
        asyncio.get_running_loop()
        # We're inside an async context with a running loop —
        # spawn a worker thread that owns its own loop so we don't deadlock.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No running loop — synchronous caller, easy case.
        return asyncio.run(coro)
