# worker/workflows/order_workflow.py
import asyncio
import uuid
from datetime import timedelta
from typing import Any

from loguru import logger
from pydantic import BaseModel, EmailStr
from temporalio import workflow
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import TLSConfig

from src.app.runtime.context import get_config
from src.app.worker.activities.example import (
    PaymentInput,
    process_payment,
    send_notification,
)
from src.app.worker.registry import workflow_defn
from src.app.worker.workflows.base import BaseWorkflow, RetryPolicy


class OrderInput(BaseModel):
    """Input for order processing workflow."""

    order_id: str
    customer_email: EmailStr
    amount: float
    items: list[dict[str, Any]]


class OrderOutput(BaseModel):
    """Output from order processing workflow."""

    order_id: str
    status: str
    total_amount: float
    message: str


@workflow_defn(queue="example")
class OrderProcessingWorkflow(BaseWorkflow[OrderInput, OrderOutput]):
    """
    Order processing workflow with full type safety.

    Demonstrates:
    - Strongly typed workflow method
    - Signal handlers for external events
    - Query handlers for state inspection
    - Activity tracking and cancellation
    """

    def __init__(self) -> None:
        super().__init__()  # Initialize BaseWorkflow tracking
        self._status: str = "initialized"
        self._cancelled: bool = False
        self._cancel_reason: str | None = None

    @workflow.run
    async def run(self, input: OrderInput) -> OrderOutput:
        """
        Main workflow execution method.

        Note: Return type is strongly typed with Pydantic model.
        """
        self._status = "processing"
        await asyncio.sleep(1)  # yield control to event loop

        try:
            # Check if cancelled before starting
            if self._cancelled:
                self._status = "cancelled"
                return OrderOutput(
                    order_id=input.order_id,
                    status="cancelled",
                    total_amount=0.0,
                    message=f"Order cancelled: {self._cancel_reason}",
                )

            # Execute payment activity with strong typing - using BaseWorkflow method
            payment_result = await self.execute_activity(
                process_payment,
                PaymentInput(order_id=input.order_id, amount=input.amount),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                ),
            )

            # Check cancellation after payment
            if self._cancelled:
                self._status = "cancelled_after_payment"
                return OrderOutput(
                    order_id=input.order_id,
                    status="cancelled_after_payment",
                    total_amount=input.amount,
                    message=f"Order cancelled after payment: {self._cancel_reason}",
                )

            self._status = "payment_completed"

            # Send notification - using BaseWorkflow method
            await self.execute_activity(
                send_notification,
                args=[
                    input.customer_email,
                    f"Order {input.order_id} processed successfully",
                ],
                start_to_close_timeout=timedelta(seconds=10),
            )

            self._status = "completed"

            return OrderOutput(
                order_id=input.order_id,
                status="completed",
                total_amount=input.amount,
                message=f"Order processed successfully. Transaction: {payment_result.transaction_id}",
            )

        except Exception as e:
            self._status = "failed"
            return OrderOutput(
                order_id=input.order_id,
                status="failed",
                total_amount=0.0,
                message=f"Order processing failed: {str(e)}",
            )

    @workflow.signal(name="cancel_order")
    def cancel_order(self, reason: str) -> None:
        """
        Signal handler to cancel the order.

        Note: Signals can be sent while workflow is running.
        This will cancel all in-flight activities via BaseWorkflow.
        """
        self._cancelled = True
        self._cancel_reason = reason
        self._status = f"cancelling: {reason}"
        # Call parent's cancel to cancel all tracked activities
        super().cancel()

    @workflow.signal(name="update_status")
    async def update_status(self, new_status: str) -> None:
        """
        Signal handler to update status.

        Note: Signal handlers can be async if needed.
        """
        self._status = f"manual_update: {new_status}"

    @workflow.query(name="get_status")
    def get_status(self) -> str:
        """
        Query handler to get current status.

        Note: Queries are read-only and return immediately.
        """
        return self._status

    @workflow.query(name="is_cancelled")
    def is_cancelled(self) -> bool:
        """Query if the workflow has been cancelled."""
        return self._cancelled


# =============================================================================
# Example 1: Blocking Workflow Execution
# =============================================================================


async def example_1_execute_workflow_blocking() -> None:
    """
    Execute a workflow and wait for completion (blocking).

    This is the simplest pattern - start workflow and wait for result.
    """
    print("\n=== Example 1: Blocking Workflow Execution ===")

    config = get_config()
    temporal_config = config.temporal

    tls = None
    if temporal_config.tls:
        if TLSConfig is None:
            logger.error(
                "TLS requested but TLSConfig is unavailable in temporalio package."
            )
            raise RuntimeError("TLSConfig unavailable")
        tls = (
            TLSConfig()
        )  # customize as needed (server_root_ca_cert, client cert/key, etc.)

    print("Connecting to Temporal server...")
    # Connect to Temporal server
    client = await Client.connect(
        temporal_config.url,
        namespace=temporal_config.namespace,
        tls=tls or False,
        data_converter=pydantic_data_converter,
    )

    # Create input with strong typing
    order_input = OrderInput(
        order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        customer_email="customer@example.com",
        amount=99.99,
        items=[{"sku": "WIDGET-1", "quantity": 2}],
    )

    print(f"Starting workflow for order {order_input.order_id}...")

    # Option 1: Start and wait for result using registry
    handle = await OrderProcessingWorkflow.start_workflow(
        client,
        order_input,
        id=f"order-workflow-{order_input.order_id}",
    )

    # Wait for the workflow to complete
    result = await handle.result()

    print(f"Workflow completed: {result.status}")
    print(f"Message: {result.message}")
    print(f"Total: ${result.total_amount}")


if __name__ == "__main__":
    print("Starting example workflow execution...")
    asyncio.run(example_1_execute_workflow_blocking())
