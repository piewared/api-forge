"""Product API router with CRUD operations.

Authentication is enforced at the router level via ``dependencies=[...]`` so
every endpoint below is authenticated by default — there's no per-endpoint
``_user`` boilerplate to forget. If a route needs the user object (audit
logging, ownership checks), declare ``user: User = Depends(get_authenticated_user)``
in that endpoint's signature; FastAPI dedupes the call within a request.

For a public endpoint, override with ``dependencies=[]`` on that route.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from src.app.api.http.deps import get_authenticated_user, get_db_session

from .repository import ProductRepository
from .schemas import ProductCreate, ProductRead, ProductUpdate
from .service import ProductNotFoundError, ProductService


def get_product_service(
    session: Session = Depends(get_db_session),
) -> ProductService:
    return ProductService(session, ProductRepository(session))


router = APIRouter(
    prefix="/api/v1/products",
    tags=["products"],
    dependencies=[Depends(get_authenticated_user)],
)


@router.post(
    "/",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    data: ProductCreate,
    service: ProductService = Depends(get_product_service),
) -> ProductRead:
    """Create a new product."""
    return service.create(data)


@router.get("/{item_id}", response_model=ProductRead)
async def get_product(
    item_id: str,
    service: ProductService = Depends(get_product_service),
) -> ProductRead:
    """Get a product by ID."""
    result = service.get(item_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return result


@router.put("/{item_id}", response_model=ProductRead)
async def update_product(
    item_id: str,
    data: ProductUpdate,
    service: ProductService = Depends(get_product_service),
) -> ProductRead:
    """Update a product (partial update — only sent fields change)."""
    try:
        return service.update(item_id, data)
    except ProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    item_id: str,
    service: ProductService = Depends(get_product_service),
) -> None:
    """Delete a product."""
    if not service.delete(item_id):
        raise HTTPException(status_code=404, detail="Product not found")


@router.get("/", response_model=list[ProductRead])
async def list_products(
    service: ProductService = Depends(get_product_service),
) -> list[ProductRead]:
    """List all products."""
    return service.list()
