"""Entity: Product."""

from typing import Any

from src.app.entities.core._base import Entity


class Product(Entity):
    """Product entity representing a product in the system.

    This is the domain model that contains business logic and validation.
    It inherits from Entity to get auto-generated UUID identifiers.
    """

    def __eq__(self, other: Any) -> bool:
        """Compare products by business attributes, ignoring timestamps."""
        if not isinstance(other, Product):
            return False

        return self.id == other.id

    def __hash__(self) -> int:
        """Hash based on business attributes, ignoring timestamps."""
        return hash((self.id,))
