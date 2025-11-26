"""Product database table model."""

from src.app.entities.core._base import EntityTable


class ProductTable(EntityTable, table=True):
    """Database persistence model for products.

    This represents how the Product entity is stored in the database.
    It's separate from the domain entity to maintain clean architecture
    while keeping related code together.
    """
