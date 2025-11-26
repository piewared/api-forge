# api/routes/workflows.py
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.app.api.http.deps import get_temporal_service
from src.app.core.services import TemporalClientService

router = APIRouter(prefix="/workflows")


class StartRequest(BaseModel):
    workflow: str  # e.g., "OrderWorkflow"
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    id: str | None = None
    task_queue: str = "app"


@router.post("/start")
async def start(
    req: StartRequest,
    client_service: TemporalClientService = Depends(get_temporal_service),
) -> dict[str, str | None]:
    wf = getattr(
        __import__("worker.workflows", fromlist=[req.workflow]), req.workflow, None
    )
    client = await client_service.get_client()
    if not wf:
        raise HTTPException(404, "Workflow type not found")

    handle = await client.start_workflow(
        wf.run,
        *req.args,
        **req.kwargs,
        id=req.id or f"{req.workflow.lower()}-{uuid.uuid4()}",
        task_queue=req.task_queue,
    )
    return {"workflow_id": handle.id, "run_id": handle.first_execution_run_id}


@router.post("/{workflow_id}/signal/{signal_name}")
async def signal(
    workflow_id: str,
    signal_name: str,
    payload: dict[str, Any],
    client_service: TemporalClientService = Depends(get_temporal_service),
) -> dict[str, bool]:
    client = await client_service.get_client()
    h = client.get_workflow_handle(workflow_id)
    await h.signal(signal_name, **payload)
    return {"ok": True}


@router.get("/{workflow_id}")
async def read(
    workflow_id: str,
    client_service: TemporalClientService = Depends(get_temporal_service),
) -> Any:
    client = await client_service.get_client()
    h = client.get_workflow_handle(workflow_id)
    return await h.query("state")
