"""Shared exception types for the CLI.

Living here (rather than inside any specific feature module) so generic
infrastructure — like the ``with_error_handling`` decorator in ``console`` —
can catch them without importing into deployment internals.
"""

from __future__ import annotations


class DeploymentError(Exception):
    """Raised when a deployment operation fails.

    Carries an optional ``details`` payload so callers (notably the
    error-handling decorator) can render a more helpful message panel
    alongside the headline.
    """

    def __init__(self, message: str, details: str | None = None) -> None:
        self.message = message
        self.details = details
        super().__init__(message)
