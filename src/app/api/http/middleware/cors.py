"""CORS configuration helper."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.app.runtime.context import get_config


def configure_cors(app: FastAPI) -> None:
    """Attach CORS middleware using the runtime config.

    In production, ``*`` is rejected when ``allow_credentials=True`` because the
    combination is forbidden by the CORS spec and silently breaks browsers.
    """
    config = get_config()

    if config.app.environment == "production" and ("*" in config.app.cors.origins):
        raise RuntimeError(
            "CORS misconfigured: cannot use '*' with allow_credentials=True in production"
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.app.cors.origins,
        allow_credentials=config.app.cors.allow_credentials,
        allow_methods=config.app.cors.allow_methods,
        allow_headers=config.app.cors.allow_headers,
    )
