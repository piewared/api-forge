"""Book repository for data access."""

from sqlmodel import Session, select

from .entity import Book
from .table import BookTable

# Server-managed columns that the repo must never overwrite from a domain
# entity. ``updated_at`` is omitted because the table's ``onupdate`` trigger
# refreshes it on flush.
_IMMUTABLE_FIELDS = frozenset({"id", "created_at"})


class BookRepository:
    """Data access layer for Book entities.

    Handles all database operations for Books while keeping the data access
    logic colocated with the Book entity. Repositories never call ``commit()``
    — the application service owns the unit of work.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, book_id: str) -> Book | None:
        """Get a book by ID."""
        row = self._session.get(BookTable, book_id)
        if row is None:
            return None
        return Book.model_validate(row, from_attributes=True)

    def create(self, book: Book) -> Book:
        """Persist a new book and return it.

        Flushes so server-generated columns (server defaults, computed columns,
        triggers) are populated and constraint errors surface synchronously
        rather than at commit time. The returned entity reflects the row as
        the database sees it, not the input.
        """
        row = BookTable.model_validate(book, from_attributes=True)
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return Book.model_validate(row, from_attributes=True)

    def update(self, book: Book) -> Book:
        """Update an existing book.

        Copies only mutable fields onto the persisted row — ``id`` and
        ``created_at`` are protected at the repo boundary so a stray service
        bug or external caller can't clobber them. ``updated_at`` is left to
        the table's ``onupdate`` trigger.
        """
        row = self._session.get(BookTable, book.id)
        if row is None:
            raise ValueError(f"Book with ID {book.id} not found")

        for field, value in book.model_dump().items():
            if field in _IMMUTABLE_FIELDS:
                continue
            setattr(row, field, value)

        self._session.flush()
        self._session.refresh(row)
        return Book.model_validate(row, from_attributes=True)

    def delete(self, book_id: str) -> bool:
        """Delete a book by ID. Returns True if deleted, False if not found."""
        row = self._session.get(BookTable, book_id)
        if row is None:
            return False
        self._session.delete(row)
        return True

    def list_all(self) -> list[Book]:
        """List all books."""
        rows = self._session.exec(select(BookTable)).all()
        return [Book.model_validate(row, from_attributes=True) for row in rows]
