"""Unit tests for the workflows management router.

The router has 3 endpoints — start / signal / query — that touch Temporal via
``TemporalClientService``. Tests mount only this router on a minimal FastAPI
app and override the temporal-service dependency with an AsyncMock.

For the start endpoint, the route resolves a workflow class by name via
``_find_workflow_class``, which scans ``src.app.worker.workflows`` for
registered ``BaseWorkflow`` subclasses. Tests patch that lookup to return
a sentinel — the function itself is exercised via integration with the
real worker package elsewhere.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.api.http.deps import get_temporal_service
from src.app.api.http.routers import workflows as workflows_module
from src.app.api.http.routers.workflows import router

# ---------- Fixtures ----------


class _FakeWorkflow:
    """Stand-in for a Temporal workflow class.

    The route only reads ``.run`` from the class as the workflow callable, so
    any sentinel attribute is fine.
    """

    __name__ = "OrderWorkflow"
    run = "fake-run-method"


@pytest.fixture
def patch_workflow_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None]:
    """Make ``_find_workflow_class`` resolve ``OrderWorkflow`` to a fake class
    and return None for everything else, mirroring real lookup semantics
    without dragging in the real worker registry's discovery."""

    def _lookup(name: str) -> type | None:
        return _FakeWorkflow if name == "OrderWorkflow" else None

    monkeypatch.setattr(workflows_module, "_find_workflow_class", _lookup)
    yield


@pytest.fixture
def temporal_client() -> AsyncMock:
    """Mock Temporal client with the methods the route invokes."""
    client = AsyncMock()
    handle = MagicMock()
    handle.id = "wf-handle-id"
    handle.first_execution_run_id = "run-id-001"
    handle.signal = AsyncMock()
    handle.query = AsyncMock(return_value={"step": "completed"})

    client.start_workflow = AsyncMock(return_value=handle)
    client.get_workflow_handle = MagicMock(return_value=handle)
    return client


@pytest.fixture
def temporal_service(temporal_client: AsyncMock) -> AsyncMock:
    """TemporalClientService that yields the mock client."""
    service = AsyncMock()
    service.get_client = AsyncMock(return_value=temporal_client)
    return service


@pytest.fixture
def workflows_app(temporal_service: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_temporal_service] = lambda: temporal_service
    return app


@pytest.fixture
def workflows_client(workflows_app: FastAPI) -> TestClient:
    return TestClient(workflows_app)


# ---------- POST /workflows/start ----------


class TestStartWorkflow:
    def test_starts_workflow_and_returns_ids(
        self,
        workflows_client: TestClient,
        temporal_client: AsyncMock,
        patch_workflow_lookup: None,
    ) -> None:
        response = workflows_client.post(
            "/workflows/start",
            json={
                "workflow": "OrderWorkflow",
                "args": [{"order_id": "ORD-1"}],
                "kwargs": {},
                "id": "explicit-wf-id",
                "task_queue": "orders",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["workflow_id"] == "wf-handle-id"
        assert body["run_id"] == "run-id-001"

        kwargs = temporal_client.start_workflow.call_args.kwargs
        assert kwargs["id"] == "explicit-wf-id"
        assert kwargs["task_queue"] == "orders"

    def test_generates_id_when_not_provided(
        self,
        workflows_client: TestClient,
        temporal_client: AsyncMock,
        patch_workflow_lookup: None,
    ) -> None:
        response = workflows_client.post(
            "/workflows/start",
            json={"workflow": "OrderWorkflow"},
        )

        assert response.status_code == 200
        kwargs = temporal_client.start_workflow.call_args.kwargs
        assert kwargs["id"].startswith("orderworkflow-")
        assert len(kwargs["id"]) > len("orderworkflow-")

    def test_unknown_workflow_returns_404(
        self,
        workflows_client: TestClient,
        patch_workflow_lookup: None,
    ) -> None:
        response = workflows_client.post(
            "/workflows/start",
            json={"workflow": "DoesNotExist"},
        )

        assert response.status_code == 404
        assert "DoesNotExist" in response.json()["detail"]


# ---------- _find_workflow_class (integration with the real registry) ----------


class TestFindWorkflowClass:
    """The lookup function itself must work against the real worker package
    so the route resolves real workflow classes in production."""

    def test_finds_real_workflow_class(self) -> None:
        from src.app.worker.workflows.example import OrderProcessingWorkflow

        result = workflows_module._find_workflow_class("OrderProcessingWorkflow")
        assert result is OrderProcessingWorkflow

    def test_returns_none_for_unknown_name(self) -> None:
        assert workflows_module._find_workflow_class("NotARealWorkflow") is None

    def test_returns_none_for_activity_with_matching_name(self) -> None:
        """``discover`` returns activities and workflows; the lookup must
        filter to BaseWorkflow subclasses to avoid resolving an activity
        as a workflow."""
        # ``process_payment`` is a registered *activity*, not a workflow.
        assert workflows_module._find_workflow_class("process_payment") is None


# ---------- POST /workflows/{id}/signal/{name} ----------


class TestSignalWorkflow:
    def test_dispatches_signal_to_handle(
        self, workflows_client: TestClient, temporal_client: AsyncMock
    ) -> None:
        response = workflows_client.post(
            "/workflows/wf-id/signal/cancel",
            json={"payload": {"reason": "user_request"}},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "cancel" in body["message"]
        assert "wf-id" in body["message"]

        temporal_client.get_workflow_handle.assert_called_once_with("wf-id")
        handle = temporal_client.get_workflow_handle.return_value
        handle.signal.assert_awaited_once_with("cancel", reason="user_request")


# ---------- GET /workflows/{id} ----------


class TestQueryWorkflow:
    def test_returns_workflow_state(
        self, workflows_client: TestClient, temporal_client: AsyncMock
    ) -> None:
        response = workflows_client.get("/workflows/wf-id")

        assert response.status_code == 200
        body = response.json()
        assert body["workflow_id"] == "wf-id"
        assert body["state"] == {"step": "completed"}

        handle = temporal_client.get_workflow_handle.return_value
        handle.query.assert_awaited_once_with("state")
