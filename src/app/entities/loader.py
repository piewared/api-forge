"""Dynamic SQLModel table loader for Alembic migrations.

This module provides automatic discovery and import of all SQLModel table
models, eliminating the need to manually update imports when new entities
are added.

SQLModel uses SQLModel.metadata (equivalent to SQLAlchemy's declarative_base().metadata)
to track all registered tables. Models register themselves when imported.
This loader ensures all table.py modules are imported.
"""

import importlib
from pathlib import Path

from sqlalchemy import MetaData
from sqlmodel import SQLModel


def get_entities_path() -> Path:
    """Get the path to the entities directory.

    Uses __file__ to be independent of package naming,
    so it works after Copier renames 'src' to the project slug.
    """
    return Path(__file__).parent


def load_all_tables() -> None:
    """Dynamically import all table.py modules to register SQLModel tables.

    This function discovers all table.py files in the entities directory
    and imports them. When a SQLModel class with `table=True` is imported,
    it automatically registers with SQLModel.metadata.

    This approach eliminates the need to manually update imports when
    adding new entities - just create the table.py file and it will
    be discovered automatically.
    """
    entities_path = get_entities_path()

    # Find this module's package name dynamically
    # This handles Copier renaming 'src' to project slug
    # __name__ will be something like 'src.app.entities.loader' or 'myproject.app.entities.loader'
    package_base = __name__.rsplit(".", 2)[0]  # e.g., 'src.app' or 'myproject.app'

    for table_file in entities_path.rglob("table.py"):
        # Convert file path to module name relative to entities directory
        relative_path = table_file.relative_to(entities_path)
        # Remove .py extension and convert path separators to dots
        module_parts = relative_path.with_suffix("").parts
        module_name = f"{package_base}.entities.{'.'.join(module_parts)}"

        try:
            importlib.import_module(module_name)
            print(f"Imported tables from {module_name}")
        except ImportError as e:
            # Re-raise with more context for debugging
            raise ImportError(
                f"Failed to import table module '{module_name}' from {table_file}: {e}"
            ) from e


def get_metadata() -> MetaData:
    """Load all tables and return SQLModel.metadata for Alembic.

    This is the main entry point for Alembic's env.py.

    Returns:
        SQLModel.metadata with all tables registered.
    """
    load_all_tables()
    return SQLModel.metadata
