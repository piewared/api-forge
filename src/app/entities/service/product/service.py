"""Product service: business logic and transaction boundary."""

from sqlmodel import Session

from .entity import Product
from .repository import ProductRepository
from .schemas import ProductCreate, ProductRead, ProductUpdate


class ProductNotFoundError(LookupError):
    """Raised when a product cannot be located by ID."""

    def __init__(self, product_id: str) -> None:
        super().__init__(f"Product with ID {product_id} not found")
        self.product_id = product_id


class ProductService:
    """Application service for Product.

    Owns the unit-of-work boundary: each public method commits on success and
    rolls back on failure. Add validation, authorization, and orchestration
    rules here — keep the router thin and the repository focused on persistence.
    """

    def __init__(self, session: Session, repository: ProductRepository) -> None:
        self._session = session
        self._repository = repository

    def create(self, data: ProductCreate) -> ProductRead:
        # Add business rules / validation here.
        product = Product(**data.model_dump())
        try:
            created = self._repository.create(product)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return ProductRead.model_validate(created)

    def get(self, product_id: str) -> ProductRead | None:
        product = self._repository.get(product_id)
        return ProductRead.model_validate(product) if product else None

    def list(self) -> list[ProductRead]:
        return [ProductRead.model_validate(p) for p in self._repository.list_all()]

    def update(self, product_id: str, data: ProductUpdate) -> ProductRead:
        existing = self._repository.get(product_id)
        if existing is None:
            raise ProductNotFoundError(product_id)

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(existing, key, value)

        try:
            updated = self._repository.update(existing)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return ProductRead.model_validate(updated)

    def delete(self, product_id: str) -> bool:
        try:
            deleted = self._repository.delete(product_id)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return deleted
