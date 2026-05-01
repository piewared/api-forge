"""Workflow scaffolding commands.

Mirrors the ``entity`` command structure: prompts for the workflow's
input fields and queue, then renders templates into the worker package.
Refuses to run when ``temporal.enabled`` is false — Temporal is the
canonical orchestrator and an in-memory substitute would silently skip
the durability guarantees real workflow code depends on.
"""

from .cli import workflow_app

__all__ = ["workflow_app"]
