# worker/workflows/base.py
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any, Self

from temporalio import workflow
from temporalio.client import Client, WorkflowHandle
from temporalio.common import Priority, RetryPolicy

# Sentinel value matching Temporal's internal default for missing arg parameter
_UNSET = object()


def default_workflow_opts() -> dict[str, Any]:
    from src.app.runtime.context import get_config

    cfg = get_config().temporal
    return {
        "execution_timeout": timedelta(seconds=cfg.workflows.execution_timeout_s),
        "run_timeout": timedelta(seconds=cfg.workflows.run_timeout_s),
        "task_timeout": timedelta(seconds=cfg.workflows.task_timeout_s),
        "retry_policy": RetryPolicy(
            maximum_attempts=cfg.workflows.retry.maximum_attempts,
            initial_interval=timedelta(
                seconds=cfg.workflows.retry.initial_interval_seconds
            ),
            backoff_coefficient=cfg.workflows.retry.backoff_coefficient,
            maximum_interval=timedelta(
                seconds=cfg.workflows.retry.maximum_interval_seconds
            ),
        ),
    }


# Use this INSIDE workflows when executing activities.
def default_activity_opts() -> dict[str, Any]:
    from src.app.runtime.context import get_config

    cfg = get_config().temporal
    return {
        "start_to_close_timeout": timedelta(
            seconds=cfg.activities.start_to_close_timeout_s
        ),
        "schedule_to_close_timeout": timedelta(
            seconds=cfg.activities.schedule_to_close_timeout_s
        ),
        "retry_policy": RetryPolicy(
            maximum_attempts=cfg.activities.retry.maximum_attempts,
            initial_interval=timedelta(
                seconds=cfg.activities.retry.initial_interval_seconds
            ),
            backoff_coefficient=cfg.activities.retry.backoff_coefficient,
            maximum_interval=timedelta(
                seconds=cfg.activities.retry.maximum_interval_seconds
            ),
            non_retryable_error_types=["ValidationError"],
        ),
    }


class BaseWorkflow[TArgs, TReturn](ABC):
    # common signal/query patterns

    def __init__(self) -> None:
        self._state: dict[str, Any] = {}
        self._activity_handles: dict[str, workflow.ActivityHandle[Any]] = {}
        self._activity_counter = 0

    @workflow.run
    @abstractmethod
    async def run(self, input: TArgs) -> TReturn: ...

    @workflow.query
    def state(self) -> dict:
        return self._state

    @workflow.signal
    def cancel(self):
        """Cancel signal that marks workflow as cancelled and cancels all in-flight activities."""
        self._state["cancelled"] = True
        # Cancel all tracked activity handles
        for activity_id, handle in self._activity_handles.items():
            if not handle.done():
                workflow.logger.info(f"Cancelling activity: {activity_id}")
                handle.cancel()

    def start_activity(
        self,
        activity: Any,
        arg: Any = _UNSET,
        *,
        args: list[Any] | None = None,
        task_queue: str | None = None,
        result_type: type | None = None,
        schedule_to_close_timeout: timedelta | None = None,
        schedule_to_start_timeout: timedelta | None = None,
        start_to_close_timeout: timedelta | None = None,
        heartbeat_timeout: timedelta | None = None,
        retry_policy: RetryPolicy | None = None,
        cancellation_type: workflow.ActivityCancellationType = workflow.ActivityCancellationType.TRY_CANCEL,
        activity_id: str | None = None,
        versioning_intent: workflow.VersioningIntent | None = None,
        summary: str | None = None,
        priority: Priority | None = None,
    ) -> workflow.ActivityHandle[Any]:
        """
        Start an activity asynchronously and return its handle.

        This method delegates to workflow.start_activity() and tracks the activity handle
        so it can be cancelled when the cancel() signal is received.

        Args:
            activity: The activity function to execute
            arg: Single argument to pass to the activity
            args: Multiple arguments to pass to the activity
            task_queue: Task queue to run the activity on
            result_type: Expected return type for type checking
            schedule_to_close_timeout: Maximum time from schedule to completion
            schedule_to_start_timeout: Maximum time from schedule to start
            start_to_close_timeout: Maximum time from start to completion
            heartbeat_timeout: Maximum time between heartbeats
            retry_policy: Retry policy for the activity
            cancellation_type: How to handle cancellation
            activity_id: Custom activity ID (auto-generated if not provided)
            versioning_intent: Versioning intent for the activity
            summary: Human-readable summary
            priority: Activity priority

        Returns:
            ActivityHandle that can be awaited for the result
        """
        # Generate activity ID if not provided
        if activity_id is None:
            self._activity_counter += 1
            activity_id = f"{activity.__name__}_{self._activity_counter}"

        # Prepare kwargs for workflow.start_activity
        # Temporal doesn't allow both arg and args to be set
        kwargs: dict[str, Any] = {
            "task_queue": task_queue,
            "result_type": result_type,
            "schedule_to_close_timeout": schedule_to_close_timeout,
            "schedule_to_start_timeout": schedule_to_start_timeout,
            "start_to_close_timeout": start_to_close_timeout,
            "heartbeat_timeout": heartbeat_timeout,
            "retry_policy": retry_policy,
            "cancellation_type": cancellation_type,
            "activity_id": activity_id,
            "versioning_intent": versioning_intent,
            "summary": summary,
            "priority": priority or Priority(),
        }

        # Only pass arg if args is not provided and arg is not the sentinel
        if args:
            kwargs["args"] = args
        elif arg is not _UNSET:
            kwargs["arg"] = arg

        # Start the activity
        handle = workflow.start_activity(activity, **kwargs)

        # Track the handle for cancellation
        self._activity_handles[activity_id] = handle

        # Clean up handle when done
        def cleanup(_):
            self._activity_handles.pop(activity_id, None)

        handle.add_done_callback(cleanup)

        return handle

    async def execute_activity(
        self,
        activity: Any,
        arg: Any = _UNSET,
        *,
        args: list[Any] | None = None,
        task_queue: str | None = None,
        result_type: type | None = None,
        schedule_to_close_timeout: timedelta | None = None,
        schedule_to_start_timeout: timedelta | None = None,
        start_to_close_timeout: timedelta | None = None,
        heartbeat_timeout: timedelta | None = None,
        retry_policy: RetryPolicy | None = None,
        cancellation_type: workflow.ActivityCancellationType = workflow.ActivityCancellationType.TRY_CANCEL,
        activity_id: str | None = None,
        versioning_intent: workflow.VersioningIntent | None = None,
        summary: str | None = None,
        priority: Priority | None = None,
    ) -> Any:
        """
        Execute an activity and wait for its completion.

        This method delegates to workflow.execute_activity() by first starting the activity
        and tracking its handle for cancellation, then awaiting its result.

        Args:
            activity: The activity function to execute
            arg: Single argument to pass to the activity
            args: Multiple arguments to pass to the activity
            task_queue: Task queue to run the activity on
            result_type: Expected return type for type checking
            schedule_to_close_timeout: Maximum time from schedule to completion
            schedule_to_start_timeout: Maximum time from schedule to start
            start_to_close_timeout: Maximum time from start to completion
            heartbeat_timeout: Maximum time between heartbeats
            retry_policy: Retry policy for the activity
            cancellation_type: How to handle cancellation
            activity_id: Custom activity ID (auto-generated if not provided)
            versioning_intent: Versioning intent for the activity
            summary: Human-readable summary
            priority: Activity priority

        Returns:
            The activity's return value
        """
        handle = self.start_activity(
            activity,
            arg,
            args=args,
            task_queue=task_queue,
            result_type=result_type,
            schedule_to_close_timeout=schedule_to_close_timeout,
            schedule_to_start_timeout=schedule_to_start_timeout,
            start_to_close_timeout=start_to_close_timeout,
            heartbeat_timeout=heartbeat_timeout,
            retry_policy=retry_policy,
            cancellation_type=cancellation_type,
            activity_id=activity_id,
            versioning_intent=versioning_intent,
            summary=summary,
            priority=priority,
        )
        return await handle

    @classmethod
    async def start_workflow(
        cls: type[Self],
        client: Client,
        input: TArgs,
        id: str,
        **workflow_kwargs,
    ) -> WorkflowHandle[Self, TReturn]:
        """
        Start a workflow execution asynchronously and return its handle. Handle can be used
        to query or signal the running workflow, or to wait for its completion with handle.result().

        Args:
            client: Connected Temporal client instance
            input: Input data for the workflow (type-checked)
            id: Unique workflow ID (used for deduplication)
            **workflow_kwargs: Additional arguments to pass to client.start_workflow
                              (e.g., task_timeout, retry_policy, memo, search_attributes)

        Returns:
            WorkflowHandle for querying/signaling the running workflow

        Raises:
            ValueError: If workflow_type has no declared queue

        Example:
            handle = await WorkflowType.start_workflow(
                client,
                OrderWorkflow,
                input=OrderInput(order_id="123", items=[...]),
                id="order-123",
                execution_timeout=timedelta(hours=1)
            )
            result = await handle.result()
        """
        q = getattr(cls, "__workflow_queue__", None)
        if not q:
            raise ValueError(f"{cls.__name__} has no declared queue")

        # Merge workflow_kwargs with defaults if needed. kwargs take precedence.
        merged = {**default_workflow_opts(), **workflow_kwargs}

        handle = await client.start_workflow(
            cls.run,
            input,
            id=id,
            task_queue=q,
            **merged,
        )

        return handle

    @classmethod
    async def execute_workflow(
        cls,
        client: Client,
        input: TArgs,
        id: str,
        **workflow_kwargs,
    ) -> TReturn:
        """
        Execute a workflow synchronously, blocking until it completes and returning the result.

        This is a convenience method that combines start_workflow() and handle.result().
        Use this when you want to wait for the workflow to finish and get the return value
        immediately, rather than working with a handle.

        Args:
            client: Connected Temporal client instance
            input: Input data for the workflow (type-checked)
            id: Unique workflow ID (used for deduplication)
            **workflow_kwargs: Additional arguments to pass to client.execute_workflow
                              (e.g., execution_timeout, retry_policy, memo, search_attributes)

        Returns:
            The workflow's return value (type TReturn)

        Raises:
            ValueError: If workflow_type has no declared queue
            WorkflowFailureError: If the workflow fails during execution

        Example:
            result = await OrderWorkflow.execute_workflow(
                client,
                input=OrderInput(order_id="123", items=[...]),
                id="order-123",
                execution_timeout=timedelta(hours=1)
            )
            print(f"Order status: {result.status}")
        """
        q = getattr(cls, "__workflow_queue__", None)
        if not q:
            raise ValueError(f"{cls.__name__} has no declared queue")

        # Merge workflow_kwargs with defaults if needed. kwargs take precedence.
        merged = {**default_workflow_opts(), **workflow_kwargs}

        result = await client.execute_workflow(
            cls.run,
            input,
            id=id,
            task_queue=q,
            **merged,
        )

        return result

    @classmethod
    async def schedule_workflow(
        cls: type[Self],
        client: Client,
        input: TArgs,
        id: str,
        start_delay: timedelta,
        **workflow_kwargs,
    ) -> WorkflowHandle[Self, TReturn]:
        """
        Schedule a workflow to start at a future time.

        Uses Temporal's start_delay feature to defer workflow execution. The workflow
        will be created immediately but will not start executing until the delay elapses.

        Args:
            client: Connected Temporal client instance
            input: Input data for the workflow (type-checked)
            id: Unique workflow ID (used for deduplication)
            start_delay: How long to wait before starting the workflow
            **workflow_kwargs: Additional arguments to pass to client.start_workflow
                              (e.g., execution_timeout, retry_policy, memo, search_attributes)

        Returns:
            WorkflowHandle for the scheduled workflow

        Raises:
            ValueError: If workflow_type has no declared queue

        Example:
            # Schedule workflow to start in 1 hour
            handle = await OrderWorkflow.schedule_workflow(
                client,
                input=OrderInput(order_id="123", items=[...]),
                id="order-123",
                start_delay=timedelta(hours=1),
                execution_timeout=timedelta(hours=2)
            )

            # Can query/signal before it starts
            status = await handle.query(OrderWorkflow.state)

            # Wait for it to complete
            result = await handle.result()
        """
        q = getattr(cls, "__workflow_queue__", None)
        if not q:
            raise ValueError(f"{cls.__name__} has no declared queue")

        # Merge workflow_kwargs with defaults if needed. kwargs take precedence.
        merged = {**default_workflow_opts(), **workflow_kwargs}

        handle = await client.start_workflow(
            cls.run,
            input,
            id=id,
            task_queue=q,
            start_delay=start_delay,
            **merged,
        )

        return handle
