"""Entity: Product."""

from src.app.entities.core._base import Entity


class Product(Entity):
    """Product entity representing a product in the system.

    This is the domain model that contains business logic and validation.
    It inherits from Entity to get auto-generated UUID identifiers.

    Compare instances by ``.id`` (or by a DTO) — Pydantic's default ``__eq__``
    is field-by-field and includes timestamps, so two instances of the same
    persisted entity loaded a microsecond apart will not compare equal.
    """
