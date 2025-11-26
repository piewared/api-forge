import asyncio
import os
import signal
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

# from loguru import logger
from temporalio.client import Client
from temporalio.worker import Worker

from src.app.worker.registry import (
    autodiscover_modules,
    get_activities_by_queue,
    get_workflows_by_queue,
)
from src.app.worker.workflows.base import BaseWorkflow


@dataclass
class Pool:
    """
    Container for workflows and activities registered to a task queue.

    Attributes:
        queue: Task queue name
        workflows: List of workflow classes registered to this queue
        activities: List of activity functions registered to this queue
    """

    queue: str
    workflows: list[type[Any]] = field(default_factory=list)
    activities: list[Callable[..., Any]] = field(default_factory=list)


class TemporalWorkerManager:
    """
    Central registry for Temporal workflows and activities.

    This class manages the lifecycle of Temporal workers, including:
    - Automatic discovery and registration of workflows/activities
    - Building worker pools per task queue
    - Starting and stopping workers with graceful shutdown
    - Type-safe workflow execution

    Attributes:
        pools: Dictionary mapping task queue names to Pool instances

    Example:
        # Create registry (auto-discovers all decorated handlers)
        registry = TemporalRegistry()

        # Start workers for specific queues
        client = await Client.connect("localhost:7233")
        await registry.run_workers(client, ["orders", "payments"])

        # Or start a workflow
        handle = await registry.start_workflow(
            client,
            OrderWorkflow,
            input={"order_id": "123"},
            id="order-123"
        )
    """

    def __init__(self, packages: list[str] | None = None):
        """
        Initialize the registry and discover all workflows/activities.

        Args:
            packages: Optional list of package paths to scan for handlers.
                     Defaults to standard worker.activities and worker.workflows.
        """
        autodiscover_modules(packages)
        self._pools = self._build_pools()

    def refresh(self):
        """
        Rebuild the internal pools from the current registry state.

        Use this if you've dynamically registered new handlers after
        initialization (though typically not needed).
        """
        self._pools = self._build_pools()

    def _build_pools(self) -> dict[str, Pool]:
        """
        Build worker pools by grouping workflows/activities by task queue.

        Returns:
            Dictionary mapping task queue names to Pool instances
        """
        pools: dict[str, Pool] = {}
        for queue, wfs in get_workflows_by_queue().items():
            for wf in sorted(wfs, key=lambda c: c.__name__):
                pool = pools.setdefault(queue, Pool(queue=queue))
                pool.workflows.append(wf)
        for queue, activities in get_activities_by_queue().items():
            for act in sorted(activities, key=lambda c: c.__name__):
                pool = pools.setdefault(queue, Pool(queue=queue))
                pool.activities.append(act)
        return pools

    def _build_worker(self, client: Client, task_queue: str) -> Worker:
        """
        Create a Temporal worker for the specified task queue.

        Args:
            client: Connected Temporal client instance
            task_queue: Task queue name to poll

        Returns:
            Configured Worker instance ready to run

        Raises:
            ValueError: If no workflows or activities are registered for the queue
            RuntimeError: If a handler's declared queue doesn't match the requested queue
        """
        pool = self._pools.get(task_queue)
        if not pool or (not pool.workflows and not pool.activities):
            raise ValueError(f"No handlers registered for queue '{task_queue}'")

        # Assert every workflow/activity in this pool actually declares this queue
        for wf in pool.workflows:
            declared = getattr(wf, "__workflow_queue__", None)
            if declared != task_queue:
                raise RuntimeError(
                    f"{wf.__name__} declares queue '{declared}', "
                    f"but worker requested '{task_queue}'"
                )

        for fn in pool.activities:
            declared = getattr(fn, "__activity_queue__", None)
            if declared != task_queue:
                raise RuntimeError(
                    f"Activity {fn.__name__} declares queue '{declared}', "
                    f"but worker requested '{task_queue}'"
                )

        # Configure workflow sandbox to passthrough loguru (it uses datetime.now() which is restricted)
        """from temporalio.worker.workflow_sandbox import (
            SandboxedWorkflowRunner,
            SandboxRestrictions,
        )

        restrictions = SandboxRestrictions.default.with_passthrough_modules("loguru")
        runner = SandboxedWorkflowRunner(restrictions=restrictions)
        """

        return Worker(
            client,
            task_queue=task_queue,
            workflows=pool.workflows,
            activities=pool.activities,
            # workflow_runner=runner,
            max_concurrent_workflow_tasks=int(os.getenv("WF_TASKS", "64")),
            max_concurrent_activities=int(os.getenv("ACT_CONCURRENCY", "200")),
        )

    async def run_worker(self, client: Client, task_queue: str) -> None:
        """
        Run a Temporal worker for a single task queue.

        This is a blocking call that runs until interrupted.

        Args:
            client: Connected Temporal client instance
            task_queue: Task queue name to poll

        Example:
            client = await Client.connect("localhost:7233")
            await registry.run_worker(client, "orders")
        """
        worker = self._build_worker(client, task_queue)
        await worker.run()

    async def run_workers(
        self,
        client: Client,
        task_queues: Sequence[str],
        stop_event: asyncio.Event | None = None,
        drain_timeout: float = 600.0,
    ) -> None:
        """
        Start multiple workers and handle graceful shutdown.

        Workers will poll their respective queues concurrently. On receiving
        SIGINT or SIGTERM (or when stop_event is set), workers will:
        1. Stop polling for new tasks
        2. Complete in-flight tasks (up to drain_timeout seconds)
        3. Exit cleanly

        Args:
            client: Connected Temporal client instance
            task_queues: List of task queue names to poll
            stop_event: Optional asyncio.Event to trigger shutdown.
                       If None, SIGINT/SIGTERM handlers are installed automatically.
            drain_timeout: Maximum seconds to wait for in-flight tasks to complete.
                          After timeout, workers are forcefully cancelled.

        Example:
            client = await Client.connect("localhost:7233")
            await registry.run_workers(
                client,
                ["orders", "payments", "notifications"],
                drain_timeout=300.0
            )
        """
        workers = [self._build_worker(client, q) for q in task_queues]
        run_tasks = [
            asyncio.create_task(w.run(), name=f"worker:{q}")
            for w, q in zip(workers, task_queues, strict=True)
        ]

        # If caller didn't supply a stop_event, install simple signal handlers
        if stop_event is None:
            stop_event = asyncio.Event()
            loop = asyncio.get_running_loop()
            for s in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(s, stop_event.set)
                except NotImplementedError:
                    # e.g., Windows or non-main thread
                    pass

        try:
            # Block until asked to stop
            await stop_event.wait()

            # Begin coordinated drain: stop polling & wait for in-flight tasks to finish
            # Shield so task cancellation doesn't interrupt the shutdown itself.
            await asyncio.wait_for(
                asyncio.shield(
                    asyncio.gather(
                        *(w.shutdown() for w in workers), return_exceptions=True
                    )
                ),
                timeout=drain_timeout,
            )

        except TimeoutError:
            # Drain took too long — cancel run loops so process can exit
            for t in run_tasks:
                t.cancel()

        finally:
            # Ensure all run() tasks complete (drained or cancelled)
            await asyncio.gather(*run_tasks, return_exceptions=True)

    async def start_workflow[TInput, TReturn](
        self,
        client: Client,
        workflow_type: type[BaseWorkflow[TInput, TReturn]],
        input: TInput,
        id: str,
        **temporal_kwargs,
    ):
        """
        Start a workflow execution with type safety.

        Args:
            client: Connected Temporal client instance
            workflow_type: Workflow class decorated with @workflow_defn
            input: Input data for the workflow (type-checked)
            id: Unique workflow ID (used for deduplication)
            **temporal_kwargs: Additional arguments to pass to client.start_workflow
                              (e.g., task_timeout, retry_policy, memo, search_attributes)

        Returns:
            WorkflowHandle for querying/signaling the running workflow

        Raises:
            ValueError: If workflow_type has no declared queue

        Example:
            handle = await registry.start_workflow(
                client,
                OrderWorkflow,
                input=OrderInput(order_id="123", items=[...]),
                id="order-123",
                execution_timeout=timedelta(hours=1)
            )
            result = await handle.result()
        """
        q = getattr(workflow_type, "__workflow_queue__", None)
        if not q:
            raise ValueError(f"{workflow_type.__name__} has no declared queue")

        handle = await client.start_workflow(
            workflow_type.run,
            input,
            id=id,
            task_queue=q,
            execution_timeout=timedelta(minutes=5),
            **temporal_kwargs,
        )

        return handle

    @property
    def pools(self) -> dict[str, Pool]:
        """
        Get the dictionary of task queues to their registered handlers.

        Returns:
            Dictionary mapping queue names to Pool instances
        """
        return self._pools
