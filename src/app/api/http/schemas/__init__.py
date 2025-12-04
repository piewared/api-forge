"""API schema definitions for HTTP endpoints.

This package contains Pydantic models for request/response schemas
used by the HTTP API layer.

Modules:
    health: Health check response models
    workflows: Temporal workflow request/response models
"""

from src.app.api.http.schemas.health import (
    AllServicesHealth,
    DatabaseHealth,
    DatabaseHealthDetailed,
    HealthCheckError,
    LivenessResponse,
    OIDCProviderHealth,
    OverallStatus,
    ReadinessResponse,
    RedisHealth,
    RedisHealthDetailed,
    ServiceHealthBase,
    ServiceStatus,
    TemporalHealth,
    TemporalHealthDetailed,
)
from src.app.api.http.schemas.workflows import (
    WorkflowExecutionError,
    WorkflowNotFoundError,
    WorkflowQueryResponse,
    WorkflowSignalRequest,
    WorkflowSignalResponse,
    WorkflowStartRequest,
    WorkflowStartResponse,
)

__all__ = [
    # Health schemas
    "ServiceStatus",
    "OverallStatus",
    "ServiceHealthBase",
    "DatabaseHealth",
    "DatabaseHealthDetailed",
    "RedisHealth",
    "RedisHealthDetailed",
    "TemporalHealth",
    "TemporalHealthDetailed",
    "OIDCProviderHealth",
    "AllServicesHealth",
    "ReadinessResponse",
    "LivenessResponse",
    "HealthCheckError",
    # Workflow schemas
    "WorkflowStartRequest",
    "WorkflowStartResponse",
    "WorkflowSignalRequest",
    "WorkflowSignalResponse",
    "WorkflowQueryResponse",
    "WorkflowNotFoundError",
    "WorkflowExecutionError",
]
