"""Book database table model."""

from src.app.entities.core._base import EntityTable


class BookTable(EntityTable, table=True):
    """Database persistence model for books.

    This represents how the Book entity is stored in the database.
    It's separate from the domain entity to maintain clean architecture
    while keeping related code together.
    """

    name: str
