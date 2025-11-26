"""Database initialization script."""

from src.app.core.services.database.db_manage import DbManageService
from src.app.core.services.database.db_session import get_config

main_config = get_config()  # Ensure config is loaded before DB init

db_manage_service = DbManageService()


def init_db() -> None:
    """Create all database tables."""
    db_manage_service.create_all()


if __name__ == "__main__":
    init_db()
