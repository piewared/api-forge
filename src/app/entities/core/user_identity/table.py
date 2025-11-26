"""User identity database table model."""

from datetime import UTC, datetime

from sqlalchemy import Column, String, UniqueConstraint
from sqlmodel import Field

from src.app.entities.core._base import EntityTable


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(UTC)


class UserIdentityTable(EntityTable, table=True):
    """Database persistence model for user identities.

    This represents how UserIdentity entities are stored in the database,
    with proper constraints and indexes for efficient querying.
    """

    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_identity_issuer_subject"),
    )

    issuer: str = Field(sa_column=Column(String(512), nullable=False, index=True))
    subject: str = Field(sa_column=Column(String(512), nullable=False, index=True))
    uid_claim: str | None = Field(
        default=None, sa_column=Column(String(512), nullable=True, index=True)
    )
    user_id: str = Field(foreign_key="usertable.id", index=True)
