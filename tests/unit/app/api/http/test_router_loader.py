"""Verify that the entity-router auto-discovery loader works.

The loader walks ``src/app/entities/**/router.py`` and registers each module's
top-level ``router: APIRouter`` attribute on the FastAPI app at startup.
This test exercises the contract — not the presence of any particular
entity. The bundled example entities (book, product) are placeholders that
users normally delete on day one; asserting their prefixes here would make
this test fail on the first real edit.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from src.app.api.http.routers.loader import (
    discover_entity_routers,
    register_entity_routers,
)


class TestRouterDiscovery:
    def test_discover_returns_list_of_apirouters(self) -> None:
        """Whatever the loader returns, every item must be a real
        ``APIRouter`` instance — the FastAPI ``include_router`` call would
        explode at boot otherwise."""
        routers = discover_entity_routers()
        assert isinstance(routers, list)
        assert all(isinstance(r, APIRouter) for r in routers)

    def test_register_mounts_each_discovered_prefix(self) -> None:
        """``register_entity_routers`` must wire every discovered router
        onto the app so its prefix is reachable. Expectations are derived
        from the discovery result so the test stays valid when users add
        or remove entities."""
        routers = discover_entity_routers()
        app = FastAPI()
        register_entity_routers(app)

        app_paths = {getattr(r, "path", "") for r in app.routes}
        for router in routers:
            assert any(path.startswith(router.prefix) for path in app_paths), (
                f"Router with prefix {router.prefix!r} contributed no routes "
                f"to the app after register_entity_routers()"
            )
