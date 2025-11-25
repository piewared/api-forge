from dataclasses import dataclass

from src.app.core.services import (
    AuthSessionService,
    DbSessionService,
    JWKSCacheInMemory,
    JwksService,
    JwtGeneratorService,
    JwtVerificationService,
    OidcClientService,
    RedisService,
    TemporalClientService,
    UserSessionService,
)
from src.app.core.services.storage.base import ApplicationStorage


@dataclass
class ApplicationDependencies:
    jwks_cache: JWKSCacheInMemory
    jwks_service: JwksService
    jwt_verify_service: JwtVerificationService
    jwt_generation_service: JwtGeneratorService
    app_storage: ApplicationStorage
    oidc_client_service: OidcClientService
    user_session_service: UserSessionService
    auth_session_service: AuthSessionService
    database_service: DbSessionService
    redis_service: RedisService | None
    temporal_service: TemporalClientService
