"""Activity scaffolding commands.

Activities are the I/O side of Temporal — plain async functions that
workflows invoke for non-deterministic work (DB writes, HTTP calls,
external service integration). This command generates a typed activity
skeleton and a matching unit test.
"""

from .cli import activity_app

__all__ = ["activity_app"]
