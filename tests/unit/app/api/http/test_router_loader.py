"""Verify that the entity-router auto-discovery loader works.

The loader walks ``src/app/entities/**/router.py`` and registers each module's
top-level ``router: APIRouter`` attribute on the FastAPI app at startup. This
test exercises the contract directly — no copier, no full app boot.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from src.app.api.http.routers.loader import (
    discover_entity_routers,
    register_entity_routers,
)


class TestRouterDiscovery:
    def test_discovers_existing_entity_routers(self) -> None:
        """The example entities (book, product) ship with routers, so they
        must always be discovered."""
        routers = discover_entity_routers()
        assert all(isinstance(r, APIRouter) for r in routers)

        prefixes = {r.prefix for r in routers}
        assert "/api/v1/books" in prefixes
        assert "/api/v1/products" in prefixes

    def test_register_attaches_routes_to_app(self) -> None:
        """Calling ``register_entity_routers`` should produce real, callable
        routes on the FastAPI app."""
        app = FastAPI()
        register_entity_routers(app)

        paths = {getattr(r, "path", "") for r in app.routes}
        # Two example entities × five CRUD endpoints each.
        assert "/api/v1/books/" in paths
        assert "/api/v1/books/{item_id}" in paths
        assert "/api/v1/products/" in paths
        assert "/api/v1/products/{item_id}" in paths
