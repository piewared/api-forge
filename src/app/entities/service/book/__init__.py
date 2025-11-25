"""Entity package: Book."""

from .entity import Book
from .repository import BookRepository
from .table import BookTable

__all__ = ["Book", "BookRepository", "BookTable"]
