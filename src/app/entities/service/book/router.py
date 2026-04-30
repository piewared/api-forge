"""Book API router with CRUD operations."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from src.app.api.http.deps import get_authenticated_user, get_db_session
from src.app.entities.core.user import User

from .repository import BookRepository
from .schemas import BookCreate, BookRead, BookUpdate
from .service import BookNotFoundError, BookService


def get_book_service(
    session: Session = Depends(get_db_session),
) -> BookService:
    return BookService(session, BookRepository(session))


router = APIRouter(prefix="/api/v1/books", tags=["books"])


@router.post(
    "/",
    response_model=BookRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_book(
    data: BookCreate,
    service: BookService = Depends(get_book_service),
    _user: User = Depends(get_authenticated_user),
) -> BookRead:
    """Create a new book."""
    return service.create(data)


@router.get("/{item_id}", response_model=BookRead)
async def get_book(
    item_id: str,
    service: BookService = Depends(get_book_service),
    _user: User = Depends(get_authenticated_user),
) -> BookRead:
    """Get a book by ID."""
    result = service.get(item_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return result


@router.put("/{item_id}", response_model=BookRead)
async def update_book(
    item_id: str,
    data: BookUpdate,
    service: BookService = Depends(get_book_service),
    _user: User = Depends(get_authenticated_user),
) -> BookRead:
    """Update a book (partial update — only sent fields change)."""
    try:
        return service.update(item_id, data)
    except BookNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(
    item_id: str,
    service: BookService = Depends(get_book_service),
    _user: User = Depends(get_authenticated_user),
) -> None:
    """Delete a book."""
    if not service.delete(item_id):
        raise HTTPException(status_code=404, detail="Book not found")


@router.get("/", response_model=list[BookRead])
async def list_books(
    service: BookService = Depends(get_book_service),
    _user: User = Depends(get_authenticated_user),
) -> list[BookRead]:
    """List all books."""
    return service.list()
