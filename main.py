"""Main entry point for infrastructure development server.

Run with: ``uvicorn main:app --reload``
"""

from src.app.api.http.app import app

__all__ = ["app"]
