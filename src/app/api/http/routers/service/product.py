"""Product API router with CRUD operations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from src.app.api.http.deps import get_session
from src.app.entities.service.product import Product, ProductRepository

router = APIRouter()


@router.post("/", response_model=Product)
def create_product(
    product: Product,
    session: Session = Depends(get_session),
) -> Product:
    """Create a new product."""
    repository = ProductRepository(session)
    created_product = repository.create(product)
    session.commit()
    return created_product


@router.get("/{item_id}", response_model=Product)
def get_product(
    item_id: str,
    session: Session = Depends(get_session),
) -> Product:
    """Get a product by ID."""
    repository = ProductRepository(session)
    product = repository.get(item_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.put("/{item_id}", response_model=Product)
def update_product(
    item_id: str,
    product_update: Product,
    session: Session = Depends(get_session),
) -> Product:
    """Update a product."""
    repository = ProductRepository(session)

    # Ensure the ID matches
    product_update.id = item_id

    try:
        updated_product = repository.update(product_update)
        session.commit()
        return updated_product
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{item_id}")
def delete_product(
    item_id: str,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Delete a product."""
    repository = ProductRepository(session)
    deleted = repository.delete(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Product not found")
    session.commit()
    return {"message": "Product deleted successfully"}


@router.get("/", response_model=list[Product])
def list_products(
    session: Session = Depends(get_session),
) -> list[Product]:
    """List all products."""
    repository = ProductRepository(session)
    return repository.list_all()
