"""Database engine and session factory used across the application."""

from loguru import logger
from sqlmodel import create_engine

from src.app.entities.loader import get_metadata
from src.app.runtime.context import get_config

main_config = get_config()


class DbManageService:
    def __init__(self) -> None:
        self._engine = create_engine(main_config.database.connection_string, echo=False)

    # Build the database URL with the resolved password
    def create_all(self) -> None:
        """Create all database tables."""
        from sqlmodel import SQLModel

        get_metadata()  # Ensure all tables are imported and registered

        SQLModel.metadata.create_all(self._engine)
        logger.info("Database initialized with tables.")
