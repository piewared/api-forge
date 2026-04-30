"""Auto-discovery for entity routers.

Walks the entities tree for any ``router.py`` whose top-level ``router``
attribute is an :class:`fastapi.APIRouter`, and registers each with the
FastAPI app at construction time. Entity packages that don't expose HTTP
endpoints (model-only) simply omit ``router.py`` and cost nothing.

This mirrors :mod:`src.app.entities.loader` (which auto-imports ``table.py``
modules for Alembic) so discovery-by-convention is consistent across the
codebase. Adding a new CRUD entity is a single ``api-forge-cli entity add``
command — no edits to ``app.py`` required.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from fastapi import APIRouter, FastAPI
from loguru import logger

from src.app.entities import loader as _entities_loader


def _package_base() -> str:
    """Return the importable package prefix that contains ``entities/``.

    The entities loader's module path is ``<base>.entities.loader``; stripping
    that suffix gives the base. This survives Copier renaming ``src/`` to the
    project package because the ``import`` above is rewritten at template time.
    """
    return _entities_loader.__name__.removesuffix(".entities.loader")


def discover_entity_routers() -> list[APIRouter]:
    """Import every ``entities/**/router.py`` and return their ``router`` attrs."""
    entities_path: Path = _entities_loader.get_entities_path()
    base = _package_base()

    routers: list[APIRouter] = []
    for router_file in sorted(entities_path.rglob("router.py")):
        relative_path = router_file.relative_to(entities_path)
        module_parts = relative_path.with_suffix("").parts
        module_name = f"{base}.entities.{'.'.join(module_parts)}"

        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            raise ImportError(
                f"Failed to import entity router '{module_name}' from {router_file}: {e}"
            ) from e

        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            routers.append(router)
            logger.debug("Discovered entity router: {}", module_name)
        else:
            logger.warning(
                "Module {} has no top-level `router: APIRouter`; skipping",
                module_name,
            )

    return routers


def register_entity_routers(app: FastAPI) -> None:
    """Auto-discover entity routers and register them with the FastAPI app."""
    for router in discover_entity_routers():
        app.include_router(router)
