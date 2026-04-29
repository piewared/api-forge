"""Tests for BaseWorkflow's activity tracking and cancellation behavior.

The activity-handle tracking and cancellation flow are real behavior (used to
cancel in-flight activities when a workflow is cancelled). The signature
parity checks against ``temporalio.workflow`` catch upstream API drift.
"""

from __future__ import annotations

import inspect

from temporalio import workflow

from src.app.worker.workflows.base import BaseWorkflow


class _ConcreteWorkflow(BaseWorkflow[str, str]):
    """Minimal concrete subclass usable for testing inherited behavior."""

    async def run(self, input: str) -> str:  # pragma: no cover - not invoked
        return input


class TestActivityTracking:
    def test_initial_tracking_state(self) -> None:
        """A fresh workflow has no in-flight activities and a zero counter."""
        wf = _ConcreteWorkflow()
        assert wf._activity_handles == {}
        assert wf._activity_counter == 0

    def test_cancel_signal_sets_state(self) -> None:
        wf = _ConcreteWorkflow()
        wf.cancel()
        assert wf._state.get("cancelled") is True


class TestSignatureParityWithTemporal:
    """Our wrappers must accept every parameter the temporalio function accepts,
    so callers never lose access to upstream features after a temporalio bump."""

    def test_start_activity_covers_temporal_params(self) -> None:
        ours = set(inspect.signature(BaseWorkflow.start_activity).parameters) - {"self"}
        upstream = set(inspect.signature(workflow.start_activity).parameters)
        missing = upstream - ours
        assert not missing, f"start_activity is missing temporal params: {missing}"

    def test_execute_activity_covers_temporal_params(self) -> None:
        ours = set(inspect.signature(BaseWorkflow.execute_activity).parameters) - {
            "self"
        }
        upstream = set(inspect.signature(workflow.execute_activity).parameters)
        missing = upstream - ours
        assert not missing, f"execute_activity is missing temporal params: {missing}"
