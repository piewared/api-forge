"""Main entry point for infrastructure development server."""

from src.app.api.http.app import (
    app,  # Infrastructure development: uvicorn src_main:app --reload
)

__all__ = ["app"]
