"""User domain entity."""

from typing import Any

from pydantic import Field

from src.app.entities.core._base import Entity


class User(Entity):
    """User entity representing a person in the system.

    This is the domain model that contains business logic and validation.
    It inherits from Entity to get auto-generated UUID identifiers.
    """

    first_name: str = Field(description="User's first name")
    last_name: str = Field(description="User's last name")
    email: str | None = Field(default=None, description="User's email address")
    phone: str | None = Field(default=None, description="User's phone number")
    address: str | None = Field(default=None, description="User's address")

    def __eq__(self, other: Any) -> bool:
        """Compare users by business attributes, ignoring timestamps."""
        if not isinstance(other, User):
            return False

        return (
            self.id == other.id
            and self.first_name == other.first_name
            and self.last_name == other.last_name
            and self.email == other.email
            and self.phone == other.phone
            and self.address == other.address
        )

    def __hash__(self) -> int:
        """Hash based on business attributes, ignoring timestamps."""
        return hash(
            (
                self.id,
                self.first_name,
                self.last_name,
                self.email,
                self.phone,
                self.address,
            )
        )
