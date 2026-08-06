"""Resolution of the development database URL for CLI workflows.

The ``prod``/``k8s``/``fly`` database commands reach their database through a
``DbRuntime``, which is PostgreSQL-shaped: it manages roles, superuser
credentials, and port-forwards. The development database has none of that — it
is whatever ``config.yaml`` resolves to for the ``development`` environment,
commonly SQLite.

This module owns that single concern: turning the development configuration
into a URL Alembic can use.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from loguru import logger

from src.app.runtime.config.config_loader import load_config
from src.infra.constants import DEFAULT_PATHS

_DEVELOPMENT = "development"
_SQLITE_SCHEME = "sqlite"


@contextmanager
def _development_environment() -> Iterator[None]:
    """Force ``APP_ENVIRONMENT=development`` for the duration of the block.

    ``load_config`` reads the environment from ``os.environ`` and promotes
    ``DEVELOPMENT_*`` variables accordingly, so the value has to be set before
    the call. The previous value is restored so a single CLI process can still
    load other environments afterwards.
    """
    previous = os.environ.get("APP_ENVIRONMENT")
    os.environ["APP_ENVIRONMENT"] = _DEVELOPMENT
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("APP_ENVIRONMENT", None)
        else:
            os.environ["APP_ENVIRONMENT"] = previous


def get_dev_database_url() -> str:
    """Return the resolved connection URL for the development database.

    Raises:
        FileNotFoundError: If config.yaml is missing.
    """
    from src.app.runtime.env_loading import load_project_env

    # Dev command by definition: .env.dev supplies placeholder values
    # for config vars with no default (e.g. OIDC client secrets).
    load_project_env(environment="development")

    config_path = DEFAULT_PATHS.config_yaml
    if not config_path.exists():
        msg = (
            f"Could not find config.yaml at {config_path}. "
            "Please ensure config.yaml exists in the project root."
        )
        raise FileNotFoundError(msg)

    # connection_string is a lazily computed field that logs while resolving the
    # password, so it must be read inside the suppression block — otherwise
    # credential-adjacent debug output leaks into CLI results.
    try:
        logger.disable("src.app.runtime")
        with _development_environment():
            config = load_config(file_path=config_path, processed=True)

            # ``database.connection_string`` resolves the password from the env
            # var or secrets file, but it unconditionally builds a
            # ``postgresql://`` URL. A project generated with use_postgres=false
            # points at SQLite, which needs no credential resolution — pass its
            # URL through untouched.
            if config.database.url.startswith(_SQLITE_SCHEME):
                return config.database.url

            return config.database.connection_string
    finally:
        logger.enable("src.app.runtime")
