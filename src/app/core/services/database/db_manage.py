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
        from sqlalchemy.exc import IntegrityError, ProgrammingError
        from sqlmodel import SQLModel

        get_metadata()  # Ensure all tables are imported and registered

        try:
            SQLModel.metadata.create_all(self._engine)
            logger.info("Database initialized with tables.")
        except (ProgrammingError, IntegrityError) as e:
            # Handle race condition when multiple workers try to create tables
            # ProgrammingError: relation already exists
            # IntegrityError: duplicate key in pg_type catalog (partial table creation)
            error_msg = str(e).lower()
            if "already exists" in error_msg or "duplicate key" in error_msg:
                logger.debug(
                    f"Tables already exist or partially created, skipping: {type(e).__name__}"
                )
            else:
                raise
