"""Product API router with CRUD operations."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from src.app.api.http.deps import get_authenticated_user, get_db_session
from src.app.entities.core.user import User

from .repository import ProductRepository
from .schemas import ProductCreate, ProductRead, ProductUpdate
from .service import ProductNotFoundError, ProductService


def get_product_service(
    session: Session = Depends(get_db_session),
) -> ProductService:
    return ProductService(session, ProductRepository(session))


router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.post(
    "/",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    data: ProductCreate,
    service: ProductService = Depends(get_product_service),
    _user: User = Depends(get_authenticated_user),
) -> ProductRead:
    """Create a new product."""
    return service.create(data)


@router.get("/{item_id}", response_model=ProductRead)
async def get_product(
    item_id: str,
    service: ProductService = Depends(get_product_service),
    _user: User = Depends(get_authenticated_user),
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
    _user: User = Depends(get_authenticated_user),
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
    _user: User = Depends(get_authenticated_user),
) -> None:
    """Delete a product."""
    if not service.delete(item_id):
        raise HTTPException(status_code=404, detail="Product not found")


@router.get("/", response_model=list[ProductRead])
async def list_products(
    service: ProductService = Depends(get_product_service),
    _user: User = Depends(get_authenticated_user),
) -> list[ProductRead]:
    """List all products."""
    return service.list()
