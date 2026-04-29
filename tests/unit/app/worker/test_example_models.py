"""Sanity tests for worker example models.

The Pydantic models in ``src.app.worker.{activities,workflows}.example`` are
plain field declarations with no custom validators. Tests that exercise
``Model(**args).field == args["field"]`` only test Pydantic itself and were
removed in a cleanup pass; the one config choice worth a regression sentinel
is ``OrderInput.customer_email: EmailStr`` — if someone downgrades it to a
plain ``str`` we want a test to catch it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.app.worker.workflows.example import OrderInput


def test_order_input_rejects_invalid_email() -> None:
    """OrderInput.customer_email must remain an EmailStr (not a plain str)."""
    with pytest.raises(ValidationError) as exc_info:
        OrderInput(
            order_id="ORD-001",
            customer_email="not-an-email",
            amount=99.99,
            items=[],
        )

    assert any(error["loc"] == ("customer_email",) for error in exc_info.value.errors())
