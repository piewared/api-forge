"""Entity: Book."""

from typing import Any

from pydantic import Field

from src.app.entities.core._base import Entity


class Book(Entity):
    """Book entity representing a book in the system.

    This is the domain model that contains business logic and validation.
    It inherits from Entity to get auto-generated UUID identifiers.
    """

    name: str = Field(description="Name")

    def __eq__(self, other: Any) -> bool:
        """Compare books by business attributes, ignoring timestamps."""
        if not isinstance(other, Book):
            return False

        return self.id == other.id and self.name == other.name

    def __hash__(self) -> int:
        """Hash based on business attributes, ignoring timestamps."""
        return hash(
            (
                self.id,
                self.name,
            )
        )
