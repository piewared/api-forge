"""Entity package: Product."""

from .entity import Product
from .repository import ProductRepository
from .table import ProductTable

__all__ = ["Product", "ProductRepository", "ProductTable"]
