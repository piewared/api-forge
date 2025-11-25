# api/routes/workflows.py
from api.deps import get_temporal_client
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from temporalio.client import Client

router = APIRouter(prefix="/workflows")

class StartRequest(BaseModel):
    workflow: str            # e.g., "OrderWorkflow"
    args: list = []
    kwargs: dict = {}
    id: str | None = None
    task_queue: str = "app"

@router.post("/start")
async def start(req: StartRequest, client: Client = Depends(get_temporal_client)):
    wf = getattr(__import__("worker.workflows", fromlist=[req.workflow]), req.workflow, None)
    if not wf: raise HTTPException(404, "Workflow type not found")
    handle = await client.start_workflow(
        wf.run, *req.args, **req.kwargs,
        id=req.id or f"{req.workflow.lower()}-{workflow.random_uuid()}",
        task_queue=req.task_queue,
    )
    return {"workflow_id": handle.id, "run_id": handle.first_execution_run_id}

@router.post("/{workflow_id}/signal/{signal_name}")
async def signal(workflow_id: str, signal_name: str, payload: dict, client: Client = Depends(get_temporal_client)):
    h = client.get_workflow_handle(workflow_id)
    await h.signal(signal_name, **payload)
    return {"ok": True}

@router.get("/{workflow_id}")
async def read(workflow_id: str, client: Client = Depends(get_temporal_client)):
    h = client.get_workflow_handle(workflow_id)
    return await h.query("state")
