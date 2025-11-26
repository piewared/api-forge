"""
Comprehensive examples of using the Temporal SDK with strong static typing.

This demonstrates best practices for:
- Executing workflows with proper type hints
- Scheduling delayed workflows
- Non-blocking workflow execution
- Signals and queries
- Cancellation and termination patterns
"""

import asyncio
import uuid
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, EmailStr
from temporalio import activity, workflow
from temporalio.api.workflowservice.v1 import ListNamespacesRequest
from temporalio.client import Client, WorkflowHandle
from temporalio.common import RetryPolicy
from temporalio.worker import Worker

# =============================================================================
# Domain Models (Pydantic for validation)
# =============================================================================


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


class PaymentInput(BaseModel):
    """Input for payment processing activity."""

    order_id: str
    amount: float


class PaymentOutput(BaseModel):
    """Output from payment processing activity."""

    transaction_id: str
    status: str


# =============================================================================
# Activities (Strongly Typed)
# =============================================================================


@activity.defn(name="process_payment")
async def process_payment(payment_input: PaymentInput) -> PaymentOutput:
    """
    Process payment for an order.

    Note: Activity signature is strongly typed with Pydantic models.
    """
    # Simulate payment processing
    await asyncio.sleep(1)

    return PaymentOutput(
        transaction_id=f"txn_{uuid.uuid4().hex[:8]}", status="completed"
    )


@activity.defn(name="send_notification")
async def send_notification(email: str, message: str) -> bool:
    """
    Send email notification.

    Note: Activity can use primitive types too.
    """
    # Simulate email sending
    await asyncio.sleep(0.5)
    print(f"Sending email to {email}: {message}")
    return True


# =============================================================================
# Workflow (Strongly Typed with Signals and Queries)
# =============================================================================


@workflow.defn(name="OrderProcessingWorkflow")
class OrderProcessingWorkflow:
    """
    Order processing workflow with full type safety.

    Demonstrates:
    - Strongly typed workflow method
    - Signal handlers for external events
    - Query handlers for state inspection
    """

    def __init__(self) -> None:
        self._status: str = "initialized"
        self._cancelled: bool = False
        self._cancel_reason: str | None = None

    @workflow.run
    async def run(self, order: OrderInput) -> OrderOutput:
        """
        Main workflow execution method.

        Note: Return type is strongly typed with Pydantic model.
        """
        self._status = "processing"

        try:
            # Check if cancelled before starting
            if self._cancelled:
                self._status = "cancelled"
                return OrderOutput(
                    order_id=order.order_id,
                    status="cancelled",
                    total_amount=0.0,
                    message=f"Order cancelled: {self._cancel_reason}",
                )

            # Execute payment activity with strong typing
            payment_result = await workflow.execute_activity(
                process_payment,
                PaymentInput(order_id=order.order_id, amount=order.amount),
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
                    order_id=order.order_id,
                    status="cancelled_after_payment",
                    total_amount=order.amount,
                    message=f"Order cancelled after payment: {self._cancel_reason}",
                )

            self._status = "payment_completed"

            # Send notification
            await workflow.execute_activity(
                send_notification,
                args=[
                    order.customer_email,
                    f"Order {order.order_id} processed successfully",
                ],
                start_to_close_timeout=timedelta(seconds=10),
            )

            self._status = "completed"

            return OrderOutput(
                order_id=order.order_id,
                status="completed",
                total_amount=order.amount,
                message=f"Order processed successfully. Transaction: {payment_result.transaction_id}",
            )

        except Exception as e:
            self._status = "failed"
            return OrderOutput(
                order_id=order.order_id,
                status="failed",
                total_amount=0.0,
                message=f"Order processing failed: {str(e)}",
            )

    @workflow.signal(name="cancel_order")
    def cancel_order(self, reason: str) -> None:
        """
        Signal handler to cancel the order.

        Note: Signals can be sent while workflow is running.
        """
        self._cancelled = True
        self._cancel_reason = reason
        self._status = f"cancelling: {reason}"

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

    # Connect to Temporal server
    client = await Client.connect("localhost:7233")

    # Create input with strong typing
    order_input = OrderInput(
        order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        customer_email="customer@example.com",
        amount=99.99,
        items=[{"sku": "WIDGET-1", "quantity": 2}],
    )

    # Execute workflow with strong typing
    # WorkflowHandle[OrderProcessingWorkflow, OrderOutput] is properly typed
    result = await client.execute_workflow(
        OrderProcessingWorkflow.run,
        order_input,
        id=f"order-workflow-{order_input.order_id}",
        task_queue="order-processing",
        execution_timeout=timedelta(minutes=5),
    )

    print(f"Workflow completed: {result.status}")
    print(f"Message: {result.message}")
    print(f"Total: ${result.total_amount}")


# =============================================================================
# Example 2: Non-Blocking Workflow Execution (Start and Get Handle)
# =============================================================================


async def example_2_start_workflow_non_blocking() -> None:
    """
    Start a workflow without waiting for completion (non-blocking).

    Returns a handle immediately that can be used to:
    - Get workflow ID
    - Wait for result later
    - Send signals
    - Query state
    - Cancel/terminate
    """
    print("\n=== Example 2: Non-Blocking Workflow Execution ===")

    client = await Client.connect("localhost:7233")

    order_input = OrderInput(
        order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        customer_email="customer@example.com",
        amount=149.99,
        items=[{"sku": "GADGET-2", "quantity": 1}],
    )

    # Start workflow and get handle immediately (non-blocking)
    # Handle is strongly typed: WorkflowHandle[OrderProcessingWorkflow, OrderOutput]
    handle = await client.start_workflow(
        OrderProcessingWorkflow.run,
        order_input,
        id=f"order-workflow-{order_input.order_id}",
        task_queue="order-processing",
        execution_timeout=timedelta(minutes=5),
    )

    print(f"Workflow started: {handle.id}")
    print("Continuing with other work...")

    # Simulate doing other work while workflow runs
    await asyncio.sleep(0.5)

    # Query the workflow status while it's running
    status = await handle.query(OrderProcessingWorkflow.get_status)
    print(f"Current status: {status}")

    # Wait for result when needed (blocks until completion)
    result = await handle.result()
    print(f"Workflow completed: {result.status}")
    print(f"Message: {result.message}")


# =============================================================================
# Example 3: Scheduled/Delayed Workflow Execution
# =============================================================================


async def example_3_schedule_delayed_workflow() -> None:
    """
    Schedule a workflow to start after a delay.

    Useful for:
    - Scheduled tasks
    - Delayed retries
    - Future execution
    """
    print("\n=== Example 3: Scheduled/Delayed Workflow Execution ===")

    client = await Client.connect("localhost:7233")

    order_input = OrderInput(
        order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        customer_email="customer@example.com",
        amount=199.99,
        items=[{"sku": "PREMIUM-3", "quantity": 1}],
    )

    # Start workflow with a delay
    handle: WorkflowHandle[
        OrderProcessingWorkflow, OrderOutput
    ] = await client.start_workflow(
        OrderProcessingWorkflow.run,
        order_input,
        id=f"order-workflow-{order_input.order_id}",
        task_queue="order-processing",
        execution_timeout=timedelta(minutes=5),
        start_delay=timedelta(seconds=10),  # Delay execution by 10 seconds
    )

    print(f"Workflow scheduled to start in 10 seconds: {handle.id}")
    print("Workflow is scheduled but not yet executing...")

    # You can still query/signal even before it starts
    # (though queries might return default values)

    # Wait for result (this will wait for delay + execution time)
    result: OrderOutput = await handle.result()
    print(f"Workflow completed: {result.status}")


# =============================================================================
# Example 4: Signals - External Events During Execution
# =============================================================================


async def example_4_send_signals_to_workflow() -> None:
    """
    Send signals to a running workflow to influence its behavior.

    Signals allow external systems to send events/data to workflows.
    """
    print("\n=== Example 4: Sending Signals to Workflow ===")

    client = await Client.connect("localhost:7233")

    order_input = OrderInput(
        order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        customer_email="customer@example.com",
        amount=299.99,
        items=[{"sku": "DELUXE-4", "quantity": 1}],
    )

    # Start workflow
    handle: WorkflowHandle[
        OrderProcessingWorkflow, OrderOutput
    ] = await client.start_workflow(
        OrderProcessingWorkflow.run,
        order_input,
        id=f"order-workflow-{order_input.order_id}",
        task_queue="order-processing",
    )

    print(f"Workflow started: {handle.id}")

    # Wait a bit for workflow to start processing
    await asyncio.sleep(0.5)

    # Send a signal to update status
    await handle.signal(
        OrderProcessingWorkflow.update_status, "customer_requested_update"
    )
    print("Sent update_status signal")

    # Query to see the updated status
    status: str = await handle.query(OrderProcessingWorkflow.get_status)
    print(f"Status after signal: {status}")

    # Let workflow complete
    result: OrderOutput = await handle.result()
    print(f"Workflow completed: {result.status}")


# =============================================================================
# Example 5: Queries - Inspect Workflow State
# =============================================================================


async def example_5_query_workflow_state() -> None:
    """
    Query a running workflow to inspect its current state.

    Queries are read-only and return immediately without affecting workflow.
    """
    print("\n=== Example 5: Querying Workflow State ===")

    client = await Client.connect("localhost:7233")

    order_input = OrderInput(
        order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        customer_email="customer@example.com",
        amount=399.99,
        items=[{"sku": "ULTIMATE-5", "quantity": 1}],
    )

    # Start workflow
    handle: WorkflowHandle[
        OrderProcessingWorkflow, OrderOutput
    ] = await client.start_workflow(
        OrderProcessingWorkflow.run,
        order_input,
        id=f"order-workflow-{order_input.order_id}",
        task_queue="order-processing",
    )

    print(f"Workflow started: {handle.id}")

    # Query workflow state multiple times during execution
    for i in range(3):
        await asyncio.sleep(0.5)

        # Multiple queries with strong typing
        status: str = await handle.query(OrderProcessingWorkflow.get_status)
        is_cancelled: bool = await handle.query(OrderProcessingWorkflow.is_cancelled)

        print(f"Check {i + 1}: Status={status}, Cancelled={is_cancelled}")

    # Wait for completion
    result: OrderOutput = await handle.result()
    print(f"Final result: {result.status}")


# =============================================================================
# Example 6: Cancellation Pattern
# =============================================================================


async def example_6_cancel_workflow() -> None:
    """
    Cancel a running workflow gracefully.

    Cancellation allows the workflow to clean up before stopping.
    """
    print("\n=== Example 6: Cancelling Workflow ===")

    client = await Client.connect("localhost:7233")

    order_input = OrderInput(
        order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        customer_email="customer@example.com",
        amount=499.99,
        items=[{"sku": "EXPENSIVE-6", "quantity": 1}],
    )

    # Start workflow
    handle: WorkflowHandle[
        OrderProcessingWorkflow, OrderOutput
    ] = await client.start_workflow(
        OrderProcessingWorkflow.run,
        order_input,
        id=f"order-workflow-{order_input.order_id}",
        task_queue="order-processing",
    )

    print(f"Workflow started: {handle.id}")

    # Send cancel signal (using our custom signal)
    await asyncio.sleep(0.3)
    await handle.signal(
        OrderProcessingWorkflow.cancel_order, "Customer requested cancellation"
    )
    print("Sent cancellation signal")

    # Alternatively, can use Temporal's built-in cancel
    # await handle.cancel()

    # Wait for workflow to complete (it will handle cancellation gracefully)
    try:
        result: OrderOutput = await handle.result()
        print(f"Workflow result after cancellation: {result.status}")
        print(f"Message: {result.message}")
    except Exception as e:
        print(f"Workflow cancelled: {e}")


# =============================================================================
# Example 7: Termination Pattern (Force Stop)
# =============================================================================


async def example_7_terminate_workflow() -> None:
    """
    Terminate a workflow forcefully (no cleanup).

    Use termination when you need to immediately stop a workflow
    without waiting for cleanup. Use sparingly.
    """
    print("\n=== Example 7: Terminating Workflow ===")

    client = await Client.connect("localhost:7233")

    order_input = OrderInput(
        order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        customer_email="customer@example.com",
        amount=599.99,
        items=[{"sku": "BROKEN-7", "quantity": 1}],
    )

    # Start workflow
    handle: WorkflowHandle[
        OrderProcessingWorkflow, OrderOutput
    ] = await client.start_workflow(
        OrderProcessingWorkflow.run,
        order_input,
        id=f"order-workflow-{order_input.order_id}",
        task_queue="order-processing",
    )

    print(f"Workflow started: {handle.id}")

    # Terminate immediately (force stop)
    await asyncio.sleep(0.2)
    await handle.terminate(reason="System maintenance - immediate shutdown required")
    print("Workflow terminated")

    # Attempting to get result will raise an exception
    try:
        result: OrderOutput = await handle.result()
        print(f"Result: {result}")
    except Exception as e:
        print(f"Expected error after termination: {type(e).__name__}")


# =============================================================================
# Example 8: Get Handle to Existing Workflow
# =============================================================================


async def example_8_get_existing_workflow_handle() -> None:
    """
    Get a handle to an already-running workflow by ID.

    Useful for:
    - Reconnecting to long-running workflows
    - Multiple services interacting with same workflow
    - Monitoring/operations
    """
    print("\n=== Example 8: Getting Handle to Existing Workflow ===")

    client = await Client.connect("localhost:7233")

    # Start a workflow
    order_input = OrderInput(
        order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        customer_email="customer@example.com",
        amount=699.99,
        items=[{"sku": "SPECIAL-8", "quantity": 1}],
    )

    workflow_id = f"order-workflow-{order_input.order_id}"

    handle1: WorkflowHandle[
        OrderProcessingWorkflow, OrderOutput
    ] = await client.start_workflow(
        OrderProcessingWorkflow.run,
        order_input,
        id=workflow_id,
        task_queue="order-processing",
    )

    print(f"Workflow started: {handle1.id}")

    # Simulate getting handle from another service/process
    # Just need the workflow ID and type information
    handle2: WorkflowHandle[OrderProcessingWorkflow, OrderOutput] = (
        client.get_workflow_handle(
            workflow_id=workflow_id,
            result_type=OrderOutput,  # Optional but helps with type safety
        )
    )

    print(f"Got handle to existing workflow: {handle2.id}")

    # Can query from the new handle
    status: str = await handle2.query(OrderProcessingWorkflow.get_status)
    print(f"Status from new handle: {status}")

    # Wait for result
    result: OrderOutput = await handle2.result()
    print(f"Result: {result.status}")


# =============================================================================
# Example 9: Workflow with Timeout Handling
# =============================================================================


async def example_9_workflow_with_timeout() -> None:
    """
    Execute workflow with timeout and handle timeout errors.

    Shows how to set execution timeouts and handle them properly.
    """
    print("\n=== Example 9: Workflow with Timeout ===")

    client = await Client.connect("localhost:7233")

    order_input = OrderInput(
        order_id=f"ORD-{uuid.uuid4().hex[:8]}",
        customer_email="customer@example.com",
        amount=799.99,
        items=[{"sku": "TIMEOUT-9", "quantity": 1}],
    )

    # Start workflow with very short timeout (for demonstration)
    handle: WorkflowHandle[
        OrderProcessingWorkflow, OrderOutput
    ] = await client.start_workflow(
        OrderProcessingWorkflow.run,
        order_input,
        id=f"order-workflow-{order_input.order_id}",
        task_queue="order-processing",
        execution_timeout=timedelta(seconds=2),  # Very short timeout
    )

    print(f"Workflow started with 2s timeout: {handle.id}")

    # Wait for result with timeout handling
    try:
        # Can also add a timeout on the result() call itself
        result: OrderOutput = await asyncio.wait_for(
            handle.result(),
            timeout=3.0,  # Wait up to 3 seconds for result
        )
        print(f"Result: {result.status}")
    except TimeoutError:
        print("Result retrieval timed out")
    except Exception as e:
        print(f"Workflow execution failed: {type(e).__name__}: {e}")


# =============================================================================
# Main: Run All Examples
# =============================================================================


async def run_all_examples() -> None:
    """Run all examples sequentially."""
    print("=" * 70)
    print("Temporal SDK Examples with Strong Static Typing")
    print("=" * 70)

    # Note: These examples assume a Temporal server and worker are running
    # In production, you'd start a worker separately

    try:
        await example_1_execute_workflow_blocking()
        await example_2_start_workflow_non_blocking()
        await example_3_schedule_delayed_workflow()
        await example_4_send_signals_to_workflow()
        await example_5_query_workflow_state()
        await example_6_cancel_workflow()
        await example_7_terminate_workflow()
        await example_8_get_existing_workflow_handle()
        await example_9_workflow_with_timeout()

    except Exception as e:
        print(f"\nError running examples: {e}")
        print("Make sure Temporal server is running and worker is started")


async def start_worker() -> None:
    """
    Start a worker to process workflows and activities.

    In production, this would typically run as a separate service.
    """
    print("\n=== Starting Temporal Worker ===")

    client = await Client.connect("localhost:7233")

    worker = Worker(
        client,
        task_queue="order-processing",
        workflows=[OrderProcessingWorkflow],
        activities=[process_payment, send_notification],
    )

    print("Worker started on task queue: order-processing")
    await worker.run()


async def check_namespaces():
    """List all namespaces in the Temporal instance."""
    client = await Client.connect("localhost:7233")

    print("=" * 70)
    print("Temporal Connection Information")
    print("=" * 70)
    print("✓ Connected to Temporal at localhost:7233")
    print(f"  Client identity: {client.identity}")
    print(f"  Default namespace: {client.namespace}")
    print()

    try:
        # List all namespaces using the workflow service
        response = await client.workflow_service.list_namespaces(
            ListNamespacesRequest(page_size=100)
        )

        print("Available Namespaces:")
        print("-" * 70)

        namespace_names = []
        if response.namespaces:
            for ns in response.namespaces:
                ns_name = ns.namespace_info.name
                namespace_names.append(ns_name)
                print(f"  • {ns_name}")
                print(f"    - ID: {ns.namespace_info.id}")
                print(f"    - State: {ns.namespace_info.state}")
                if ns.namespace_info.description:
                    print(f"    - Description: {ns.namespace_info.description}")
                print()
        else:
            print("  No namespaces found via list API")

        print(f"Total namespaces returned by API: {len(response.namespaces)}")
        print()
        print("📝 Observation:")
        print(f"   - The client's default namespace is: '{client.namespace}'")

        if client.namespace in namespace_names:
            print(f"   - The '{client.namespace}' namespace IS in the list above")
        else:
            print(f"   - The '{client.namespace}' namespace is NOT in the list above")
            print(
                "   - This may be normal depending on your Temporal server configuration"
            )

    except Exception as e:
        print(f"Error listing namespaces: {e}")
        print("\nNote: Listing namespaces may require specific permissions.")
        print("You can still use the default namespace for workflows.")


if __name__ == "__main__":
    # To run examples:
    # 1. Start Temporal server (temporal server start-dev)
    # 2. Start worker in one terminal: python temporal_sdk_examples.py worker
    # 3. Run examples in another terminal: python temporal_sdk_examples.py examples

    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        asyncio.run(start_worker())
    else:
        asyncio.run(run_all_examples())
