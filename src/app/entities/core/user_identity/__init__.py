"""User identity entity module.

This module contains all UserIdentity-related classes organized by responsibility:
- UserIdentity: Domain entity linking external auth to internal users
- UserIdentityTable: Database persistence model
- UserIdentityRepository: Data access layer
"""

from .entity import UserIdentity
from .repository import UserIdentityRepository
from .table import UserIdentityTable

__all__ = ["UserIdentity", "UserIdentityTable", "UserIdentityRepository"]
