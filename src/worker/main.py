# worker/main.py

"""
Temporal worker process entrypoint.
Starts workers for all discovered task queues or specified queues.
Handles graceful shutdown on SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import Sequence

import typer
from loguru import logger
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

try:
    # Only needed if you actually use TLS
    from temporalio.service import TLSConfig
except Exception:  # pragma: no cover
    TLSConfig = None  # type: ignore[assignment, misc]

from src.app.runtime.config.config_data import ConfigData
from src.app.runtime.context import get_config
from src.app.worker.manager import (
    TemporalWorkerManager,  # your registry (with autodiscovery)
)

app = typer.Typer(no_args_is_help=True, add_completion=False)


async def _run_workers(
    manager: TemporalWorkerManager,
    client: Client,
    task_queues: Sequence[str],
    drain_timeout: float,
) -> None:
    """Start workers for queues and drain gracefully on SIGINT/SIGTERM."""
    workers: list[Worker] = [manager._build_worker(client, q) for q in task_queues]
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
        logger.error("Temporal is disabled by configuration.")
        raise typer.Exit(code=2)

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
