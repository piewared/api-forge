"""Factory for obtaining the appropriate session storage backend."""

from typing import TYPE_CHECKING, Optional

from src.app.core.services.storage.base import ApplicationStorage
from src.app.core.services.storage.memory import InMemoryStorage
from src.app.core.services.storage.session import SessionStorage

if TYPE_CHECKING:
    from src.app.core.services.redis_service import RedisService

def get_storage(redis: Optional['RedisService']) -> ApplicationStorage:
    """Get the configured session storage instance."""

    if redis and (client := redis.get_client()):
        from src.app.core.services.storage.redis import RedisStorage

        return RedisStorage(client)

    return InMemoryStorage()


def get_session_storage(redis: Optional['RedisService']) -> SessionStorage:
    """Get the configured session storage instance."""

    storage = get_storage(redis)
    return SessionStorage(storage)
