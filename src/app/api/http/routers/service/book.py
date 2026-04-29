"""Book API router with CRUD operations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from src.app.api.http.deps import get_authenticated_user, get_db_session
from src.app.entities.core.user import User
from src.app.entities.service.book import Book, BookRepository

router = APIRouter()


@router.post("/", response_model=Book)
async def create_book(
    book: Book,
    session: Session = Depends(get_db_session),
    _user: User = Depends(get_authenticated_user),
) -> Book:
    """Create a new book."""
    repository = BookRepository(session)
    created_book = repository.create(book)
    session.commit()
    return created_book


@router.get("/{item_id}", response_model=Book)
async def get_book(
    item_id: str,
    session: Session = Depends(get_db_session),
    _user: User = Depends(get_authenticated_user),
) -> Book:
    """Get a book by ID."""
    repository = BookRepository(session)
    book = repository.get(item_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@router.put("/{item_id}", response_model=Book)
async def update_book(
    item_id: str,
    book_update: Book,
    session: Session = Depends(get_db_session),
    _user: User = Depends(get_authenticated_user),
) -> Book:
    """Update a book."""
    repository = BookRepository(session)

    # Ensure the ID matches
    book_update.id = item_id

    try:
        updated_book = repository.update(book_update)
        session.commit()
        return updated_book
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{item_id}")
async def delete_book(
    item_id: str,
    session: Session = Depends(get_db_session),
    _user: User = Depends(get_authenticated_user),
) -> dict[str, str]:
    """Delete a book."""
    repository = BookRepository(session)
    deleted = repository.delete(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Book not found")
    session.commit()
    return {"message": "Book deleted successfully"}


@router.get("/", response_model=list[Book])
async def list_books(
    session: Session = Depends(get_db_session),
    _user: User = Depends(get_authenticated_user),
) -> list[Book]:
    """List all books."""
    repository = BookRepository(session)
    return repository.list_all()
