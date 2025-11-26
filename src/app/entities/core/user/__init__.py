"""User entity module.

This module contains all User-related classes organized by responsibility:
- User: Domain entity with business logic
- UserTable: Database persistence model
- UserRepository: Data access layer

This structure keeps all User-related code together while maintaining
separation of concerns within the module.
"""

from .entity import User
from .repository import UserRepository
from .table import UserTable

__all__ = ["User", "UserTable", "UserRepository"]
