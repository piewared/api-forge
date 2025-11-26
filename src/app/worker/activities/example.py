# worker/activities/payments.py
import asyncio
import uuid

from pydantic.main import BaseModel

from src.app.worker.registry import activity_defn


class PaymentInput(BaseModel):
    """Input for payment processing activity."""

    order_id: str
    amount: float


class PaymentOutput(BaseModel):
    """Output from payment processing activity."""

    transaction_id: str
    status: str


@activity_defn(queue="example")
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


@activity_defn(queue="example")
async def send_notification(email: str, message: str) -> bool:
    """
    Send email notification.

    Note: Activity can use primitive types too.
    """
    # Simulate email sending
    await asyncio.sleep(0.5)
    print(f"Sending email to {email}: {message}")
    return True


@activity_defn(queue="example")
async def long_running_activity(duration_seconds: int) -> str:
    """
    A long-running activity for testing cancellation.

    This activity sleeps for the specified duration, making it easy to
    test activity cancellation by sending a cancel signal during execution.

    Args:
        duration_seconds: How long the activity should run

    Returns:
        A completion message
    """
    await asyncio.sleep(duration_seconds)
    return f"Completed after {duration_seconds} seconds"
