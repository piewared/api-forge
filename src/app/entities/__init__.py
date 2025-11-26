"""Entities module with hybrid entity-centric structure.

This module organizes entities by business concept rather than technical layer.
Each entity has its own package containing:
- entity.py: Domain model with business logic
- table.py: Database persistence model
- repository.py: Data access layer

This approach provides:
- High cohesion: All related code is colocated
- Separation of concerns: Each file has a single responsibility
- Easy discovery: Find everything about User in entities.user
- Clean imports: Import what you need from the entity package
"""

from .core.user import User, UserRepository, UserTable
from .core.user_identity import UserIdentity, UserIdentityRepository, UserIdentityTable

__all__ = [
    "User",
    "UserTable",
    "UserRepository",
    "UserIdentity",
    "UserIdentityTable",
    "UserIdentityRepository",
]
