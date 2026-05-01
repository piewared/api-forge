"""Lock in: the Temporal workflows router is intentionally NOT registered.

Exposing ``/workflows/start``, ``/workflows/list``, etc. over HTTP is a
real attack surface (callers can kick off arbitrary Temporal workflows).
The template defers that decision to the user — the router exists in
``src/app/api/http/routers/workflows.py`` but ``app.py`` only imports
the auth and health routers in ``_register_core_routers``.

This test asserts that contract so the design choice doesn't drift
silently. If you intentionally enable workflow management over HTTP,
delete this test and gate the registration on
``config.temporal.enabled`` in ``_register_core_routers``.
"""

from __future__ import annotations

import pytest

from src.app.api.http.app import app


@pytest.mark.parametrize(
    "path",
    [
        "/workflows/start",
        "/workflows/list",
        "/workflows/get",
        "/workflows/signal",
        "/workflows/query",
    ],
)
def test_workflows_route_not_registered(path: str) -> None:
    """No registered route should match a /workflows/* path."""
    matched = [r for r in app.routes if getattr(r, "path", "").startswith("/workflows")]
    assert not matched, (
        f"Found unexpected workflows routes: {[r.path for r in matched]}. "
        "If you intentionally exposed Temporal workflows over HTTP, update "
        "this test and ensure the registration is gated on "
        "config.temporal.enabled."
    )
