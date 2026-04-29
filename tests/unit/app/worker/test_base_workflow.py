"""Tests for BaseWorkflow utility helpers that don't require the Temporal runtime.

The valuable assertions here are the ones that catch drift between our defaults
and the temporalio API surface (signature validity) plus our deliberate retry
policy choices. ``hasattr``/``isinstance(timedelta)`` style tests just exercise
Python's stdlib and were removed.
"""

from __future__ import annotations

import inspect

import pytest
from temporalio import workflow
from temporalio.client import Client

from src.app.worker.workflows.base import (
    BaseWorkflow,
    default_activity_opts,
    default_workflow_opts,
)


class TestDefaultWorkflowOptions:
    """default_workflow_opts() must stay compatible with the temporalio client API."""

    def test_keys_accepted_by_start_workflow(self) -> None:
        sig = inspect.signature(Client.start_workflow)
        valid_params = {
            name
            for name in sig.parameters
            if name not in ("self", "workflow", "arg", "args")
        }
        invalid = set(default_workflow_opts()) - valid_params
        assert not invalid, f"unknown keys vs Client.start_workflow: {invalid}"

    def test_keys_accepted_by_execute_workflow(self) -> None:
        sig = inspect.signature(Client.execute_workflow)
        valid_params = {
            name
            for name in sig.parameters
            if name not in ("self", "workflow", "arg", "args")
        }
        invalid = set(default_workflow_opts()) - valid_params
        assert not invalid, f"unknown keys vs Client.execute_workflow: {invalid}"


class TestDefaultActivityOptions:
    """default_activity_opts() must stay compatible with workflow.execute_activity
    and encode our retry policy commitments."""

    def test_keys_accepted_by_execute_activity(self) -> None:
        sig = inspect.signature(workflow.execute_activity)
        valid_params = {
            name for name in sig.parameters if name not in ("activity", "arg", "args")
        }
        invalid = set(default_activity_opts()) - valid_params
        assert not invalid, f"unknown keys vs workflow.execute_activity: {invalid}"

    def test_retry_policy_max_attempts_is_5(self) -> None:
        """5 retries is a deliberate config choice — guard against drift."""
        retry_policy = default_activity_opts()["retry_policy"]
        assert retry_policy.maximum_attempts == 5

    def test_retry_policy_does_not_retry_validation_errors(self) -> None:
        """ValidationError must remain non-retryable: bad input never succeeds via retry."""
        retry_policy = default_activity_opts()["retry_policy"]
        assert "ValidationError" in retry_policy.non_retryable_error_types

    def test_schedule_to_close_is_at_least_start_to_close(self) -> None:
        """Real invariant: schedule_to_close must allow at least one full attempt."""
        opts = default_activity_opts()
        assert opts["schedule_to_close_timeout"] >= opts["start_to_close_timeout"]


class TestBaseWorkflowMetadata:
    def test_base_workflow_cannot_be_instantiated_directly(self) -> None:
        """BaseWorkflow has abstract methods; instantiation must fail."""
        with pytest.raises(TypeError):
            BaseWorkflow()  # pyright: ignore[reportAbstractUsage]
