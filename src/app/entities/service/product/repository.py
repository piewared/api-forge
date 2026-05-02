"""Product repository for data access."""

from sqlmodel import Session, select

from .entity import Product
from .table import ProductTable

# Server-managed columns that the repo must never overwrite from a domain
# entity. ``updated_at`` is omitted because the table's ``onupdate`` trigger
# refreshes it on flush.
_IMMUTABLE_FIELDS = frozenset({"id", "created_at"})


class ProductRepository:
    """Data access layer for Product entities.

    Handles all database operations for Products while keeping the data access
    logic colocated with the Product entity. Repositories never call
    ``commit()`` — the application service owns the unit of work.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, product_id: str) -> Product | None:
        """Get a product by ID."""
        row = self._session.get(ProductTable, product_id)
        if row is None:
            return None
        return Product.model_validate(row, from_attributes=True)

    def create(self, product: Product) -> Product:
        """Persist a new product and return it.

        Flushes so server-generated columns (server defaults, computed columns,
        triggers) are populated and constraint errors surface synchronously
        rather than at commit time. The returned entity reflects the row as
        the database sees it, not the input.
        """
        row = ProductTable.model_validate(product, from_attributes=True)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return Product.model_validate(row, from_attributes=True)

    def update(self, product: Product) -> Product:
        """Update an existing product.

        Copies only mutable fields onto the persisted row — ``id`` and
        ``created_at`` are protected at the repo boundary so a stray service
        bug or external caller can't clobber them. ``updated_at`` is left to
        the table's ``onupdate`` trigger.
        """
        row = self._session.get(ProductTable, product.id)
        if row is None:
            raise ValueError(f"Product with ID {product.id} not found")

        for field, value in product.model_dump().items():
            if field in _IMMUTABLE_FIELDS:
                continue
            setattr(row, field, value)

        self._session.flush()
        self._session.refresh(row)
        return Product.model_validate(row, from_attributes=True)

    def delete(self, product_id: str) -> bool:
        """Delete a product by ID. Returns True if deleted, False if not found."""
        row = self._session.get(ProductTable, product_id)
        if row is None:
            return False
        self._session.delete(row)
        return True

    def list_all(self) -> list[Product]:
        """List all products."""
        rows = self._session.exec(select(ProductTable)).all()
        return [Product.model_validate(row, from_attributes=True) for row in rows]
