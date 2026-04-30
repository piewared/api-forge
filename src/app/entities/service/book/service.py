"""Book service: business logic and transaction boundary."""

from sqlmodel import Session

from .entity import Book
from .repository import BookRepository
from .schemas import BookCreate, BookRead, BookUpdate


class BookNotFoundError(LookupError):
    """Raised when a book cannot be located by ID."""

    def __init__(self, book_id: str) -> None:
        super().__init__(f"Book with ID {book_id} not found")
        self.book_id = book_id


class BookService:
    """Application service for Book.

    Owns the unit-of-work boundary: each public method commits on success and
    rolls back on failure. Add validation, authorization, and orchestration
    rules here — keep the router thin and the repository focused on persistence.
    """

    def __init__(self, session: Session, repository: BookRepository) -> None:
        self._session = session
        self._repository = repository

    def create(self, data: BookCreate) -> BookRead:
        # Add business rules / validation here.
        book = Book(**data.model_dump())
        try:
            created = self._repository.create(book)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return BookRead.model_validate(created)

    def get(self, book_id: str) -> BookRead | None:
        book = self._repository.get(book_id)
        return BookRead.model_validate(book) if book else None

    def list(self) -> list[BookRead]:
        return [BookRead.model_validate(b) for b in self._repository.list_all()]

    def update(self, book_id: str, data: BookUpdate) -> BookRead:
        existing = self._repository.get(book_id)
        if existing is None:
            raise BookNotFoundError(book_id)

        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(existing, key, value)

        try:
            updated = self._repository.update(existing)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return BookRead.model_validate(updated)

    def delete(self, book_id: str) -> bool:
        try:
            deleted = self._repository.delete(book_id)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return deleted
