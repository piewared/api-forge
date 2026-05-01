# worker/main.py

"""
Temporal worker process entrypoint.
Starts workers for all discovered task queues or specified queues.
Handles graceful shutdown on SIGINT/SIGTERM.

Imports of ``temporalio`` are deferred inside function bodies so this
module stays importable when the dep is absent (``use_temporal=false``).
The ``serve`` command itself fails fast with a clear message in that case.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import typer
from loguru import logger

from src.app.runtime.config.config_data import ConfigData
from src.app.runtime.context import get_config

if TYPE_CHECKING:
    # Type-only imports — never executed at runtime, so they don't pull
    # ``temporalio`` into the import graph.
    pass

app = typer.Typer(no_args_is_help=True, add_completion=False)


async def _run_workers(
    manager: Any,
    client: Any,
    task_queues: Sequence[str],
    drain_timeout: float,
) -> None:
    """Start workers for queues and drain gracefully on SIGINT/SIGTERM."""
    # Type-only references; the actual classes come from the manager / client
    # passed in by the caller, which lazy-imports temporalio after the
    # ``temporal.enabled`` gate has confirmed the dep is available.
    workers: list[Any] = [manager._build_worker(client, q) for q in task_queues]
    run_tasks = [
        asyncio.create_task(w.run(), name=f"worker:{q}")
        for w, q in zip(workers, task_queues, strict=True)
    ]

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, stop_event.set)
        except NotImplementedError:
            # Windows / non-main thread
            pass

    logger.info("Workers started; polling queues: {}", ", ".join(task_queues))
    try:
        await stop_event.wait()
        logger.info(
            "Shutdown signal received; draining workers (timeout: {}s)...",
            drain_timeout,
        )

        await asyncio.wait_for(
            asyncio.shield(
                asyncio.gather(*(w.shutdown() for w in workers), return_exceptions=True)
            ),
            timeout=drain_timeout,
        )
        logger.info("Workers drained cleanly.")
    except TimeoutError:
        logger.warning(
            "Drain timed out after {}s; cancelling run loops.", drain_timeout
        )
        for t in run_tasks:
            t.cancel()
    finally:
        await asyncio.gather(*run_tasks, return_exceptions=True)
        logger.info("Worker event loops exited.")


@app.command(name="serve")
def serve(
    queue: list[str] | None = typer.Option(
        None,
        "--queue",
        "-q",
        help="Task queue to poll (repeatable). If omitted, polls ALL discovered queues.",
    ),
    drain_timeout: float = typer.Option(
        600.0, "--drain-timeout", help="Seconds to wait for graceful drain on shutdown."
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        case_sensitive=False,
        help="Logging level (TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL).",
    ),
) -> None:
    """
    Start a Temporal worker process.
    """
    # Configure logging
    logger.remove()
    logger.add(
        sink=sys.stderr,
        level=log_level.upper(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - "
        "<level>{message}</level>",
        colorize=True,
    )

    # Load config
    config: ConfigData = get_config()
    temporal_config = config.temporal

    if not temporal_config.enabled:
        logger.error(
            "Temporal is disabled by configuration "
            "(temporal.enabled=false). Worker cannot start. "
            "Set temporal.enabled=true and ensure the temporalio package is "
            "installed (use_temporal=true at template generation time)."
        )
        raise typer.Exit(code=2)

    # Defer ``temporalio``-touching imports until after the enabled-gate so
    # this module stays importable when the dep was stripped.
    try:
        from temporalio.client import Client
        from temporalio.contrib.pydantic import pydantic_data_converter

        try:
            from temporalio.service import TLSConfig
        except Exception:  # pragma: no cover
            TLSConfig = None  # type: ignore[assignment, misc]

        from src.app.worker.manager import TemporalWorkerManager
    except ImportError as exc:
        logger.error(
            "temporalio is not installed. Run with use_temporal=true at "
            "template generation, or `uv add temporalio` to install it. "
            f"Original error: {exc}"
        )
        raise typer.Exit(code=2) from exc

    # Discover queues from code (single source of truth)
    manager = TemporalWorkerManager()
    discovered = sorted(manager.pools.keys())
    if not discovered:
        logger.error(
            "No queues discovered. Define @workflow_defn/@activity_defn in your code."
        )
        raise typer.Exit(code=2)

    if queue:
        unknown = [q for q in queue if q not in discovered]
        if unknown:
            logger.error(
                "Unknown queue(s): {}. Known: {}",
                ", ".join(unknown),
                ", ".join(discovered),
            )
            raise typer.Exit(code=2)
        queues = queue
    else:
        queues = discovered

    # Connect Temporal client (TLS optional)
    logger.info(
        "Connecting to Temporal: url={}, namespace={}, tls={}",
        temporal_config.url,
        temporal_config.namespace,
        temporal_config.tls,
    )
    tls = None
    if temporal_config.tls:
        if TLSConfig is None:
            logger.error(
                "TLS requested but TLSConfig is unavailable in temporalio package."
            )
            raise typer.Exit(code=2)
        tls = (
            TLSConfig()
        )  # customize as needed (server_root_ca_cert, client cert/key, etc.)

    async def _amain() -> int:
        client = await Client.connect(
            temporal_config.url,
            namespace=temporal_config.namespace,
            tls=tls or False,
            data_converter=pydantic_data_converter,
        )
        try:
            await _run_workers(manager, client, queues, drain_timeout)
            return 0
        except Exception:
            logger.exception("Worker crashed")
            return 1

    raise typer.Exit(code=asyncio.run(_amain()))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
