"""Pydantic schemas for workflow API endpoints.

This module defines request and response models for the Temporal workflow
management API endpoints.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# Request Models
# =============================================================================


class WorkflowStartRequest(BaseModel):
    """Request model for starting a new workflow.

    Example:
        ```json
        {
            "workflow": "OrderWorkflow",
            "args": [{"order_id": "123"}],
            "task_queue": "orders"
        }
        ```
    """

    workflow: str = Field(
        description="Name of the workflow class to execute (e.g., 'OrderWorkflow')"
    )
    args: list[Any] = Field(
        default_factory=list,
        description="Positional arguments to pass to the workflow",
    )
    kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Keyword arguments to pass to the workflow",
    )
    id: str | None = Field(
        default=None,
        description="Custom workflow ID. If not provided, one is auto-generated.",
    )
    task_queue: str = Field(
        default="app",
        description="Temporal task queue to use for the workflow",
    )


class WorkflowSignalRequest(BaseModel):
    """Request model for signaling a workflow.

    Signals are async messages that can be sent to running workflows
    to trigger state changes or actions.
    """

    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Data payload to send with the signal",
    )


# =============================================================================
# Response Models
# =============================================================================


class WorkflowStartResponse(BaseModel):
    """Response model for a successfully started workflow."""

    workflow_id: str = Field(description="Unique identifier for the workflow")
    run_id: str | None = Field(
        default=None,
        description="Temporal run ID for this workflow execution",
    )


class WorkflowSignalResponse(BaseModel):
    """Response model for a successful signal operation."""

    success: bool = Field(
        default=True,
        description="Whether the signal was sent successfully",
    )
    message: str = Field(
        default="Signal sent",
        description="Status message",
    )


class WorkflowQueryResponse(BaseModel):
    """Response model for a workflow query.

    The actual structure depends on the workflow's query handler,
    but this provides a typed wrapper.
    """

    state: Any = Field(description="Current workflow state from the query")
    workflow_id: str | None = Field(
        default=None,
        description="Workflow ID that was queried",
    )


class WorkflowNotFoundError(BaseModel):
    """Error response when a workflow type is not found."""

    detail: str = Field(description="Error message describing what went wrong")
    available_workflows: list[str] | None = Field(
        default=None,
        description="List of available workflow types",
    )


class WorkflowExecutionError(BaseModel):
    """Error response for workflow execution failures."""

    detail: str = Field(description="Error message")
    workflow_id: str | None = Field(
        default=None,
        description="Workflow ID if available",
    )
    error_type: str | None = Field(
        default=None,
        description="Type of error that occurred",
    )
