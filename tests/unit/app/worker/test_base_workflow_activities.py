"""Unit tests for BaseWorkflow activity tracking methods.

Tests the start_activity() and execute_activity() methods that track in-flight
activities for cancellation support.
"""

import pytest


class TestBaseWorkflowActivityMethods:
    """Test BaseWorkflow activity tracking and cancellation."""

    def test_base_workflow_has_start_activity_method(self):
        """Test BaseWorkflow has start_activity instance method."""
        from src.app.worker.workflows.base import BaseWorkflow

        assert hasattr(BaseWorkflow, "start_activity")
        # Note: Can't test callable directly since it's on abstract class

    def test_base_workflow_has_execute_activity_method(self):
        """Test BaseWorkflow has execute_activity instance method."""
        from src.app.worker.workflows.base import BaseWorkflow

        assert hasattr(BaseWorkflow, "execute_activity")

    def test_base_workflow_tracks_activity_handles(self):
        """Test BaseWorkflow initializes activity handle tracking."""
        from src.app.worker.workflows.base import BaseWorkflow

        # Create a concrete implementation for testing
        class TestWorkflow(BaseWorkflow[str, str]):
            async def run(self, input: str) -> str:
                return input

        workflow = TestWorkflow()

        # Verify tracking data structures exist
        assert hasattr(workflow, "_activity_handles")
        assert isinstance(workflow._activity_handles, dict)
        assert len(workflow._activity_handles) == 0

        assert hasattr(workflow, "_activity_counter")
        assert workflow._activity_counter == 0

    def test_start_activity_signature(self):
        """Test start_activity has the expected signature with all Temporal parameters."""
        import inspect

        from src.app.worker.workflows.base import BaseWorkflow

        sig = inspect.signature(BaseWorkflow.start_activity)
        params = list(sig.parameters.keys())

        # Verify key parameters are present
        assert "self" in params
        assert "activity" in params
        assert "arg" in params
        assert "args" in params
        assert "task_queue" in params
        assert "schedule_to_close_timeout" in params
        assert "start_to_close_timeout" in params
        assert "retry_policy" in params
        assert "cancellation_type" in params
        assert "activity_id" in params
        assert "priority" in params

    def test_execute_activity_signature(self):
        """Test execute_activity has the expected signature with all Temporal parameters."""
        import inspect

        from src.app.worker.workflows.base import BaseWorkflow

        sig = inspect.signature(BaseWorkflow.execute_activity)
        params = list(sig.parameters.keys())

        # Verify key parameters are present
        assert "self" in params
        assert "activity" in params
        assert "arg" in params
        assert "args" in params
        assert "task_queue" in params
        assert "schedule_to_close_timeout" in params
        assert "start_to_close_timeout" in params
        assert "retry_policy" in params
        assert "cancellation_type" in params
        assert "activity_id" in params
        assert "priority" in params

    def test_execute_activity_is_async(self):
        """Test execute_activity is an async method."""
        import inspect

        from src.app.worker.workflows.base import BaseWorkflow

        assert inspect.iscoroutinefunction(BaseWorkflow.execute_activity)

    def test_start_activity_is_not_async(self):
        """Test start_activity is a regular method (returns handle, not awaitable)."""
        import inspect

        from src.app.worker.workflows.base import BaseWorkflow

        # start_activity should NOT be async - it returns an ActivityHandle
        assert not inspect.iscoroutinefunction(BaseWorkflow.start_activity)

    def test_cancel_signal_implementation(self):
        """Test cancel signal sets state and would cancel activities."""
        from src.app.worker.workflows.base import BaseWorkflow

        # Create a concrete implementation for testing
        class TestWorkflow(BaseWorkflow[str, str]):
            async def run(self, input: str) -> str:
                return input

        workflow = TestWorkflow()

        # Call cancel signal
        workflow.cancel()

        # Verify state was updated
        assert workflow._state.get("cancelled") is True

    def test_start_activity_signature_matches_temporal(self):
        """Test start_activity signature matches Temporal's workflow.start_activity."""
        import inspect

        from temporalio import workflow

        from src.app.worker.workflows.base import BaseWorkflow

        base_sig = inspect.signature(BaseWorkflow.start_activity)
        temporal_sig = inspect.signature(workflow.start_activity)

        base_params = set(base_sig.parameters.keys()) - {"self"}
        temporal_params = set(temporal_sig.parameters.keys())

        # All Temporal parameters should be in BaseWorkflow method
        # (BaseWorkflow may have additional ones like self)
        missing_params = temporal_params - base_params
        assert not missing_params, (
            f"Missing parameters from Temporal API: {missing_params}"
        )

    def test_execute_activity_signature_matches_temporal(self):
        """Test execute_activity signature matches Temporal's workflow.execute_activity."""
        import inspect

        from temporalio import workflow

        from src.app.worker.workflows.base import BaseWorkflow

        base_sig = inspect.signature(BaseWorkflow.execute_activity)
        temporal_sig = inspect.signature(workflow.execute_activity)

        base_params = set(base_sig.parameters.keys()) - {"self"}
        temporal_params = set(temporal_sig.parameters.keys())

        # All Temporal parameters should be in BaseWorkflow method
        missing_params = temporal_params - base_params
        assert not missing_params, (
            f"Missing parameters from Temporal API: {missing_params}"
        )


class TestActivityTrackingDocumentation:
    """Test that methods have proper documentation."""

    def test_start_activity_has_docstring(self):
        """Test start_activity has docstring explaining tracking."""
        from src.app.worker.workflows.base import BaseWorkflow

        assert BaseWorkflow.start_activity.__doc__ is not None
        docstring = BaseWorkflow.start_activity.__doc__
        assert "track" in docstring.lower() or "cancel" in docstring.lower()

    def test_execute_activity_has_docstring(self):
        """Test execute_activity has docstring explaining tracking."""
        from src.app.worker.workflows.base import BaseWorkflow

        assert BaseWorkflow.execute_activity.__doc__ is not None
        docstring = BaseWorkflow.execute_activity.__doc__
        assert "track" in docstring.lower() or "cancel" in docstring.lower()

    def test_cancel_signal_has_docstring(self):
        """Test cancel signal has docstring explaining activity cancellation."""
        from src.app.worker.workflows.base import BaseWorkflow

        assert BaseWorkflow.cancel.__doc__ is not None
        docstring = BaseWorkflow.cancel.__doc__
        assert "cancel" in docstring.lower()
        assert "activity" in docstring.lower() or "activities" in docstring.lower()
