"""Temporal workflow management endpoints.

This module provides HTTP endpoints for managing Temporal workflows,
including starting workflows, sending signals, and querying workflow state.

Endpoint Summary:
    POST /workflows/start      - Start a new workflow
    POST /workflows/{id}/signal/{name} - Send signal to a running workflow
    GET  /workflows/{id}       - Query workflow state
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from src.app.api.http.deps import get_temporal_service
from src.app.api.http.schemas.workflows import (
    WorkflowNotFoundError,
    WorkflowQueryResponse,
    WorkflowSignalRequest,
    WorkflowSignalResponse,
    WorkflowStartRequest,
    WorkflowStartResponse,
)
from src.app.core.services import TemporalClientService

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post(
    "/start",
    response_model=WorkflowStartResponse,
    responses={
        404: {
            "description": "Workflow type not found",
            "model": WorkflowNotFoundError,
        },
    },
    summary="Start a new workflow",
    description="Start a new Temporal workflow execution with the specified parameters.",
)
async def start_workflow(
    request: WorkflowStartRequest,
    client_service: TemporalClientService = Depends(get_temporal_service),
) -> WorkflowStartResponse:
    """Start a new Temporal workflow.

    Looks up the workflow class by name from the worker.workflows module
    and starts a new execution with the provided arguments.

    Args:
        request: Workflow start parameters including workflow name and arguments

    Returns:
        WorkflowStartResponse with the workflow ID and run ID

    Raises:
        HTTPException: 404 if the workflow type is not found
    """
    # Dynamic import of workflow class
    try:
        workflow_module = __import__("worker.workflows", fromlist=[request.workflow])
        workflow_class = getattr(workflow_module, request.workflow, None)
    except ImportError:
        workflow_class = None

    if not workflow_class:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow type '{request.workflow}' not found",
        )

    client = await client_service.get_client()

    # Generate workflow ID if not provided
    workflow_id = request.id or f"{request.workflow.lower()}-{uuid.uuid4()}"

    handle = await client.start_workflow(
        workflow_class.run,
        *request.args,
        **request.kwargs,
        id=workflow_id,
        task_queue=request.task_queue,
    )

    return WorkflowStartResponse(
        workflow_id=handle.id,
        run_id=handle.first_execution_run_id,
    )


@router.post(
    "/{workflow_id}/signal/{signal_name}",
    response_model=WorkflowSignalResponse,
    summary="Signal a running workflow",
    description="Send a signal to a running workflow to trigger state changes or actions.",
)
async def signal_workflow(
    workflow_id: str,
    signal_name: str,
    request: WorkflowSignalRequest,
    client_service: TemporalClientService = Depends(get_temporal_service),
) -> WorkflowSignalResponse:
    """Send a signal to a running workflow.

    Signals are async messages that workflows can handle to trigger
    state changes, continue waiting operations, or perform actions.

    Args:
        workflow_id: ID of the running workflow
        signal_name: Name of the signal to send
        request: Signal payload

    Returns:
        WorkflowSignalResponse indicating success
    """
    client = await client_service.get_client()
    handle = client.get_workflow_handle(workflow_id)

    await handle.signal(signal_name, **request.payload)

    return WorkflowSignalResponse(
        success=True,
        message=f"Signal '{signal_name}' sent to workflow '{workflow_id}'",
    )


@router.get(
    "/{workflow_id}",
    response_model=WorkflowQueryResponse,
    summary="Query workflow state",
    description="Query the current state of a workflow using the 'state' query handler.",
)
async def query_workflow(
    workflow_id: str,
    client_service: TemporalClientService = Depends(get_temporal_service),
) -> WorkflowQueryResponse:
    """Query a workflow's current state.

    Uses the 'state' query handler defined in the workflow to retrieve
    the current workflow state.

    Args:
        workflow_id: ID of the workflow to query

    Returns:
        WorkflowQueryResponse with the workflow state
    """
    client = await client_service.get_client()
    handle = client.get_workflow_handle(workflow_id)

    state = await handle.query("state")

    return WorkflowQueryResponse(
        state=state,
        workflow_id=workflow_id,
    )
