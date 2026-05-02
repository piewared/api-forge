# FastAPI Clean Architecture Overview

API Forge organises code in concentric layers so business rules stay
independent of FastAPI, the database, and external services. New entities are
scaffolded with all five layers in place, ready to grow.

> **Framing.** This is *layered clean architecture*, not strict
> hexagonal/ports-and-adapters. The application service receives a concrete
> `sqlmodel.Session` rather than an abstract `UnitOfWork` port — a deliberate
> pragmatic compromise that keeps the scaffold short and avoids a layer of
> indirection most teams never need. If you require a strict port-and-adapter
> seam (e.g., to swap persistence engines or run domain tests against an
> in-memory unit of work), introduce it on the entities you need it for; the
> scaffold won't fight you.

## The five files per entity

When you run `api-forge-cli entity add Widget`, the scaffold drops a single
self-contained package:

```
src/app/entities/service/widget/
├── entity.py      # Domain model (Pydantic) — business invariants and identity
├── table.py       # Persistence model (SQLModel) — how the entity is stored
├── repository.py  # Data access — CRUD against the table
├── schemas.py     # Request/response DTOs (Create, Read, Update)
├── service.py     # Application service — business logic + transactions
├── router.py      # FastAPI endpoints — auto-discovered at startup
└── __init__.py    # Re-exports the entity, repository, and table
```

Dependencies flow **inward**: outer layers depend on inner layers, never the
reverse.

```
HTTP request
   │
   ▼  router.py
   │   ┌─ Schemas (Create / Read / Update DTOs)
   │   └─ Depends(get_<entity>_service)
   ▼  service.py
   │   ├─ Owns the transaction (commit / rollback)
   │   └─ Calls repository
   ▼  repository.py
   │   └─ SQLModel operations on table.py
   ▼  table.py + entity.py
       └─ Persistence + domain model
```

## Two kinds of services

The codebase uses the word "service" in two distinct roles. They live in
different places.

| Where | What | Examples |
|---|---|---|
| `src/app/core/services/` | **Infrastructure services** — cross-cutting adapters used by the whole app | JWT verification, OIDC clients, Redis, session storage, Temporal client |
| `src/app/entities/<group>/<name>/service.py` | **Application services** — per-entity business logic and transaction boundaries | `BookService`, `WidgetService`, `UserManagementService` |

When this guide says "service layer" it always means the latter.

## Entity vs. table

API Forge keeps two distinct models per entity:

- **`entity.py` — the domain `Entity`** is a pure Pydantic model. Business
  invariants and identity live here. The domain code never sees an ORM.
- **`table.py` — the `EntityTable`** is a SQLModel that maps the entity onto
  a database table. The `entities/loader.py` discovery walks every `table.py`
  so Alembic sees new tables without manual registration.

This split is intentional: persistence concerns (column types, server-side
defaults, indices) don't leak into the domain, and the domain doesn't pull
SQLAlchemy into every consumer.

```python
# entity.py
from pydantic import Field
from src.app.entities.core._base import Entity


class Widget(Entity):
    title: str = Field(description="Title")
    price: float | None = Field(default=None, description="Price")
```

```python
# table.py
from src.app.entities.core._base import EntityTable


class WidgetTable(EntityTable, table=True):
    title: str
    price: float | None = None
```

## Repository

Pure persistence: take a session, return / accept domain entities. No business
rules; no HTTP types.

```python
# repository.py
from sqlmodel import Session

from .entity import Widget
from .table import WidgetTable


class WidgetRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, widget_id: str) -> Widget | None:
        row = self._session.get(WidgetTable, widget_id)
        if row is None:
            return None
        return Widget.model_validate(row, from_attributes=True)

    def create(self, widget: Widget) -> Widget:
        row = WidgetTable.model_validate(widget, from_attributes=True)
        self._session.add(row)
        return widget

    def list_all(self) -> list[Widget]:
        rows = self._session.query(WidgetTable).all()
        return [Widget.model_validate(r, from_attributes=True) for r in rows]
```

Repositories never call `commit()`. Transactions are owned by the layer above.

## Schemas (DTOs)

Inbound and outbound payloads are separate Pydantic models so server-managed
fields (`id`, `created_at`, `updated_at`) can't be set by clients and so the
API surface evolves independently of the persistence model.

```python
# schemas.py
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class WidgetCreate(BaseModel):
    title: str
    price: float | None = None


class WidgetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime
    title: str
    price: float | None = None


class WidgetUpdate(BaseModel):
    """Partial-update payload — every field optional."""
    title: str | None = None
    price: float | None = None
```

## Service (application layer)

The service holds the **unit of work**: each public method commits on success
and rolls back on failure. Add validation, authorization, and orchestration
across multiple repositories here. Errors raised by the service use
domain-level exception types — the router translates them to HTTP responses.

```python
# service.py
from sqlmodel import Session

from .entity import Widget
from .repository import WidgetRepository
from .schemas import WidgetCreate, WidgetRead, WidgetUpdate


class WidgetNotFoundError(LookupError):
    def __init__(self, widget_id: str) -> None:
        super().__init__(f"Widget with ID {widget_id} not found")
        self.widget_id = widget_id


class WidgetService:
    def __init__(self, session: Session, repository: WidgetRepository) -> None:
        self._session = session
        self._repository = repository

    def create(self, data: WidgetCreate) -> WidgetRead:
        # Add business rules / validation here.
        widget = Widget(**data.model_dump())
        try:
            created = self._repository.create(widget)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return WidgetRead.model_validate(created)

    def update(self, widget_id: str, data: WidgetUpdate) -> WidgetRead:
        existing = self._repository.get(widget_id)
        if existing is None:
            raise WidgetNotFoundError(widget_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(existing, key, value)
        try:
            updated = self._repository.update(existing)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return WidgetRead.model_validate(updated)
```

> **Why services own transactions.** Putting `session.commit()` in the router
> couples HTTP and persistence: a single endpoint can't atomically span
> several repository calls without leaking session details up the stack.
> Services are also the natural seam for retries, idempotency tokens, and
> Temporal workflow handoffs.

## Router (HTTP layer)

The router is thin: validate input via DTOs, depend on the service, translate
domain exceptions to HTTP responses. No business rules, no `session.commit()`.

```python
# router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from src.app.api.http.deps import get_db_session

from .repository import WidgetRepository
from .schemas import WidgetCreate, WidgetRead, WidgetUpdate
from .service import WidgetNotFoundError, WidgetService


def get_widget_service(session: Session = Depends(get_db_session)) -> WidgetService:
    return WidgetService(session, WidgetRepository(session))


router = APIRouter(prefix="/api/v1/widgets", tags=["widgets"])


@router.post("/", response_model=WidgetRead, status_code=status.HTTP_201_CREATED)
def create_widget(
    data: WidgetCreate,
    service: WidgetService = Depends(get_widget_service),
) -> WidgetRead:
    return service.create(data)


@router.put("/{item_id}", response_model=WidgetRead)
def update_widget(
    item_id: str,
    data: WidgetUpdate,
    service: WidgetService = Depends(get_widget_service),
) -> WidgetRead:
    try:
        return service.update(item_id, data)
    except WidgetNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
```

The `prefix` and `tags` are declared on the router itself — there's no
matching `app.include_router(...)` line in `app.py` to keep in sync.

## Auto-discovery

`src/app/api/http/routers/loader.py` walks `entities/**/router.py` at startup
and registers every module-level `router` it finds. Adding a new entity is a
single CLI invocation — no edits to `app.py`. Likewise,
`src/app/entities/loader.py` walks `entities/**/table.py` so Alembic sees new
tables automatically.

## Generating a new entity

```bash
api-forge-cli entity add Widget
```

The CLI prompts for fields, then renders all six files using the templates in
`src/cli/templates/*.j2`. Restart the dev server and the new endpoints are
live at `/api/v1/widgets/`.

To remove an entity:

```bash
api-forge-cli entity rm Widget
```

This deletes the package directory; the router disappears with it.

## Testing each layer

| Layer | Test type | Approach |
|---|---|---|
| Entity | Unit | Pure Pydantic — validate invariants directly |
| Repository | Integration | In-memory SQLite session, exercise real SQL |
| Service | Unit | Mock the repository, assert commit on success / rollback on failure |
| Router | Integration | `TestClient`, override `get_<entity>_service` to a stub |

Service tests are the highest-value-per-line: they exercise business logic
without booting FastAPI or hitting a database.

## Async work: Temporal vs. BackgroundTasks

Two ways to run async work from a request handler. Pick based on the
guarantees you actually need:

| Need                                         | Use                              |
|----------------------------------------------|----------------------------------|
| Durable execution; survives crashes/restarts | **Temporal workflow**            |
| Retries with exponential backoff             | **Temporal workflow**            |
| Schedules / cron-style recurring             | **Temporal workflow**            |
| Long-running (minutes to days)               | **Temporal workflow**            |
| Cross-process coordination                   | **Temporal workflow**            |
| Fire-and-forget, no guarantees needed        | FastAPI **`BackgroundTasks`**    |
| Send a confirmation email after request      | FastAPI **`BackgroundTasks`**    |
| Hash a small payload off the request path    | FastAPI **`BackgroundTasks`**    |

Both primitives are triggered from a route handler — the difference is in
how much structure each requires.

**Use Temporal** for anything where losing the work on a process restart
would be wrong: order processing, payment flows, anything that touches
external systems with retry semantics. The route handler delegates to a
service method, which holds the workflow-start. Scaffold with
`api-forge-cli workflow add <Name>` (and matching activities), or in one
shot via `api-forge-cli entity add Order --with-workflow OrderDispatch`.

```python
# router.py — thin handler, delegates to the service
@router.post("/orders/{order_id}/dispatch", response_model=DispatchResponse)
async def dispatch_order(
    order_id: str,
    service: OrderService = Depends(get_order_service),
) -> DispatchResponse:
    return await service.dispatch(order_id)


# service.py — owns the workflow-start (gets temporal via DI)
async def dispatch(self, order_id: str) -> DispatchResponse:
    client = await self._temporal.get_client()
    handle = await OrderDispatchWorkflow.start_workflow(
        client,
        input=OrderDispatchInput(order_id=order_id),
        id=f"order-dispatch-{order_id}",  # idempotent: dedupes retries
    )
    return DispatchResponse(workflow_id=handle.id)
```

**Use `BackgroundTasks`** when fire-and-forget really is enough. It's
shipped with FastAPI, takes one import, and is honest about what it
gives you (a best-effort coroutine that runs after the response is sent;
no retries, no durability).

```python
# router.py — same handler shape, but the async dispatch happens
# inline via the FastAPI-supplied BackgroundTasks instance
from fastapi import BackgroundTasks

@router.post("/widgets/", response_model=WidgetRead, status_code=201)
async def create_widget(
    data: WidgetCreate,
    bg: BackgroundTasks,
    service: WidgetService = Depends(get_widget_service),
) -> WidgetRead:
    widget = service.create(data)
    bg.add_task(send_welcome_email, widget.email)  # fire-and-forget
    return widget
```

The asymmetry is intentional. Temporal earns its own service method
because there's real surface area to encapsulate — typed input,
idempotency ID, retry policy, signal/query handlers later on. Fire-and-
forget is a one-liner; it doesn't need its own seam, and pushing
`BackgroundTasks` down into the service would couple the service to
FastAPI's request lifecycle for no benefit.

If `BackgroundTasks` isn't enough but Temporal is too much, that's the
moment to reach for a job queue (Celery, Dramatiq, RQ). The template
doesn't ship one — the pattern matters, the choice doesn't.

> ⚠️ The template intentionally does **not** ship an in-memory
> "workflow executor" that swaps in for Temporal when it's disabled. The
> contract Temporal provides — durable execution — can't be fulfilled by
> an in-process substitute, and silently dropping that guarantee in dev
> would be a foot-gun. When `temporal.enabled=false`, the workflow and
> activity scaffolding commands refuse to run.

## Anti-patterns to avoid

❌ **`session.commit()` in router handlers.** It scatters transaction
boundaries across the HTTP layer and makes multi-step writes impossible to
keep atomic.

❌ **Domain entity as request/response body.** Clients can post
`id`/`created_at`/`updated_at`, and the persistence model becomes an
inadvertent public API. Always use the `Create`/`Read`/`Update` DTOs.

❌ **HTTP exceptions inside the service.** `HTTPException` is a FastAPI
concept — services should raise domain errors (e.g.
`WidgetNotFoundError`) and let the router translate to status codes.

❌ **Business logic in the repository.** Repositories return entities; they
don't decide whether an operation is allowed.

## See also

- [Sessions and Cookies](./fastapi-sessions-and-cookies.md)
- [Authentication & OIDC](./fastapi-auth-oidc-bff.md)
- [Temporal Workflows](./fastapi-temporal-workflows.md)
- [Testing Strategy](./fastapi-testing-strategy.md)
