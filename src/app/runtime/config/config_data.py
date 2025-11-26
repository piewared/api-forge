"""Pydantic models for parsing the config.yaml configuration file.

This module contains Pydantic models that correspond to the structure of config.yaml.
These models handle validation and type conversion of the YAML configuration data.
"""

from __future__ import annotations

from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field, computed_field


def deep_freeze(value: Any) -> Any:
    """Recursively convert mutable containers into hashable equivalents."""
    if isinstance(value, dict):
        return tuple(sorted((k, deep_freeze(v)) for k, v in value.items()))
    elif isinstance(value, (list, tuple)):
        return tuple(deep_freeze(v) for v in value)
    elif isinstance(value, set):
        return frozenset(deep_freeze(v) for v in value)
    else:
        return value  # primitive types are already hashable


class CORSConfig(BaseModel):
    """CORS configuration for the application."""

    origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:3001"]
    )
    allow_credentials: bool = True
    allow_methods: list[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )
    allow_headers: list[str] = Field(default=["*"])


class RateLimiterConfig(BaseModel):
    """Rate limiter configuration model."""

    requests: int = Field(
        default=100, description="Number of requests allowed per window"
    )
    window_ms: int = Field(default=60000, description="Time window in milliseconds")
    enabled: bool = Field(default=True, description="Enable rate limiting")
    per_endpoint: bool = Field(
        default=True, description="Apply rate limiting per endpoint"
    )
    per_method: bool = Field(
        default=True, description="Apply rate limiting per HTTP method"
    )


class TemporalWorkerConfig(BaseModel):
    """Temporal worker configuration model."""

    enabled: bool = Field(default=True, description="Enable temporal worker")
    activities_per_second: int = Field(
        default=10, description="Activities per second limit"
    )
    max_concurrent_activities: int = Field(
        default=100, description="Maximum concurrent activities"
    )
    max_concurrent_workflows: int = Field(
        default=100, description="Maximum concurrent workflows"
    )
    poll_interval_ms: int = Field(
        default=1000, description="Poll interval in milliseconds"
    )
    workflow_cache_size: int = Field(default=100, description="Workflow cache size")
    max_workflow_tasks_per_second: int = Field(
        default=100, description="Maximum workflow tasks per second"
    )
    max_concurrent_workflow_tasks: int = Field(
        default=100, description="Maximum concurrent workflow tasks"
    )
    sticky_queue_schedule_to_start_timeout_ms: int = Field(
        default=10000,
        description="Sticky queue schedule to start timeout in milliseconds",
    )
    worker_build_id: str = Field(default="api-worker-1", description="Worker build ID")


class TemporalyRetryConfig(BaseModel):
    """Temporal activity retry policy configuration model."""

    maximum_attempts: int = Field(
        default=5,
        description="Maximum number of retry attempts for activities",
    )
    initial_interval_seconds: int = Field(
        default=5,
        description="Initial interval in seconds between retries",
    )
    backoff_coefficient: float = Field(
        default=2.0,
        description="Backoff coefficient for retry intervals",
    )
    maximum_interval_seconds: int = Field(
        default=60,
        description="Maximum interval in seconds between retries",
    )


class TemporalActivitiesConfig(BaseModel):
    """Temporal activities configuration model."""

    start_to_close_timeout_s: int = Field(
        default=1200,
        description="Start to close timeout in seconds for activities",
    )
    schedule_to_close_timeout_s: int = Field(
        default=3600,
        description="Schedule to close timeout in seconds for activities. Includes retries",
    )
    heartbeat_timeout_s: int = Field(
        default=300,
        description="Heartbeat timeout in seconds for activities",
    )
    retry: TemporalyRetryConfig = Field(
        default_factory=lambda: TemporalyRetryConfig(),
        description="Retry policy for activities",
    )


class TemporalWorkflowsConfig(BaseModel):
    """Temporal workflows configuration model."""

    execution_timeout_s: int = Field(
        default=86400,
        description="Total workflow execution timeout including retries and continue as new",
    )
    run_timeout_s: int = Field(
        default=7200,
        description="Timeout of a single workflow run.",
    )
    task_timeout_s: int = Field(
        default=10,
        description="Timeout of a single workflow task.",
    )
    retry: TemporalyRetryConfig = Field(
        default_factory=lambda: TemporalyRetryConfig(),
        description="Retry policy for workflows",
    )


class TemporalConfig(BaseModel):
    """Temporal configuration model."""

    tls: bool = Field(default=False, description="Enable TLS for Temporal connection")
    enabled: bool = Field(default=True, description="Enable temporal service")
    url: str = Field(default="temporal:7233", description="Temporal server url")
    namespace: str = Field(default="default", description="Temporal namespace")
    task_queue: str = Field(default="default", description="Temporal task queue name")
    worker: TemporalWorkerConfig = Field(
        default_factory=TemporalWorkerConfig, description="Worker configuration"
    )
    activities: TemporalActivitiesConfig = Field(
        default_factory=TemporalActivitiesConfig, description="Activities configuration"
    )
    workflows: TemporalWorkflowsConfig = Field(
        default_factory=TemporalWorkflowsConfig, description="Workflows configuration"
    )


class RedisConfig(BaseModel):
    """Redis configuration model."""

    enabled: bool = Field(default=True, description="Enable Redis service")
    url: str = Field(default="", description="Redis connection URL")
    password: str | None = Field(
        default=None, description="Password for Redis authentication"
    )
    decode_responses: bool = Field(
        default=True, description="Decode Redis responses to strings"
    )
    max_connections: int = Field(
        default=10, description="Maximum number of connections in the pool"
    )
    socket_timeout: int = Field(
        default=5, description="Socket timeout in seconds for Redis operations"
    )
    socket_connect_timeout: int = Field(
        default=5, description="Socket connect timeout in seconds for Redis"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def connection_string(self) -> str:
        """Construct the Redis connection string with password if provided."""
        if self.password:
            if "@" in self.url:
                # URL already has auth info
                return self.url
            parts = self.url.split("://", 1)
            if len(parts) == 2:
                from urllib.parse import quote_plus

                scheme, rest = parts
                # URL-encode password to handle special characters like /, @, :, etc.
                encoded_password = quote_plus(self.password)
                return f"{scheme}://:{encoded_password}@{rest}"
        return self.url

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sanitized_connection_string(self) -> str:
        """Get connection string with password masked for safe logging."""
        conn_str = self.connection_string
        if ":" in conn_str and "@" in conn_str:
            # Format: redis://:PASSWORD@host:port/db
            # Split on LAST @ (password might contain @)
            parts = conn_str.rsplit("@", 1)
            if len(parts) == 2:
                prefix = parts[0].split(":")[0]  # Get scheme (redis://)
                return f"{prefix}:****@{parts[1]}"
        return conn_str


class OIDCProviderConfig(BaseModel):
    """OIDC provider configuration model."""

    openid_configuration_endpoint: str | None = Field(
        default=None, description="URL to fetch OIDC provider configuration"
    )
    authorization_endpoint: str = Field(description="OIDC authorization endpoint URL")
    token_endpoint: str = Field(description="OIDC token endpoint URL")
    userinfo_endpoint: str | None = Field(
        default=None, description="OIDC userinfo endpoint URL"
    )
    end_session_endpoint: str | None = Field(
        default=None, description="OIDC end session endpoint URL"
    )
    issuer: str = Field(description="OIDC issuer URL")
    jwks_uri: str = Field(description="JWKS endpoint for JWT validation")
    scopes: list[str] = Field(
        default_factory=lambda: ["openid", "profile", "email"],
        description="OIDC scopes to request during authentication",
    )
    client_id: str = Field(description="Client ID for the OIDC provider")
    client_secret: str = Field(description="Client secret for the OIDC provider")
    redirect_uri: str = Field(description="Redirect URI for this provider")
    enabled: bool = Field(default=True, description="Enable OIDC authentication")
    dev_only: bool = Field(
        default=True, description="Enable OIDC only in development environment"
    )


class OIDCRefreshTokenPolicy(BaseModel):
    """Controls whether refresh tokens are issued and stored."""

    enabled: bool = Field(
        default=False,
        description="Allow the BFF to accept and use refresh tokens from providers",
    )
    persist_in_session_store: bool = Field(
        default=False,
        description="If enabled, persist refresh tokens in the user session for reuse",
    )
    max_session_lifetime_seconds: int = Field(
        default=86400,
        description="Maximum lifetime of a session that can request refresh (prevents indefinite refresh)",
    )


class OIDCConfig(BaseModel):
    """OIDC configuration model."""

    providers: dict[str, OIDCProviderConfig] = Field(
        default_factory=dict, description="OIDC provider configurations"
    )
    default_provider: str = Field(
        default="keycloak", description="Default OIDC provider to use"
    )
    global_redirect_uri: str = Field(
        default="http://localhost:8000/auth/callback",
        description="Global fallback redirect URI for all providers",
    )
    allowed_redirect_hosts: list[str] = Field(
        default_factory=list,
        description="Allowed hosts for absolute redirect URLs (empty = relative only)",
    )
    allowed_audiences: list[str] = Field(
        default_factory=list,
        description="Allowed audiences for validating incoming ID tokens (empty = skip audience check)",
    )
    refresh_tokens: OIDCRefreshTokenPolicy = Field(
        default_factory=OIDCRefreshTokenPolicy,
        description="Refresh token policy and storage controls",
    )


class JWTClaimsConfig(BaseModel):
    """JWT claims mapping configuration."""

    user_id: str = Field(
        default="sub", description="Claim name for user ID (usually 'sub')"
    )
    email: str = Field(default="email", description="Claim name for email address")
    roles: str = Field(
        default="roles", description="Claim name for user roles/permissions"
    )
    groups: str = Field(default="groups", description="Claim name for user groups")
    scope: str = Field(default="scope", description="Claim name for OAuth scopes")
    name: str = Field(default="name", description="Claim name for user's full name")
    preferred_username: str = Field(
        default="preferred_username", description="Claim name for username"
    )


class JWTConfig(BaseModel):
    """JWT validation configuration."""

    allowed_algorithms: list[str] = Field(
        default_factory=lambda: ["RS256", "RS512", "ES256", "ES384"],
        description="JWT algorithms allowed for token validation",
    )
    gen_issuer: str = Field(
        default="my-api-issuer", description="Issuer name to use when generating tokens"
    )
    audiences: list[str] = Field(
        default_factory=lambda: ["api://default"],
        description="JWT audiences that this API accepts",
    )
    clock_skew: int = Field(default=60, description="Clock skew tolerance in seconds")
    verify_signature: bool = Field(default=True, description="Verify JWT signature")
    verify_exp: bool = Field(default=True, description="Verify token expiration")
    verify_nbf: bool = Field(default=True, description="Verify not-before claim")
    verify_iat: bool = Field(default=True, description="Verify issued-at claim")
    require_exp: bool = Field(default=True, description="Require expiration claim")
    require_iat: bool = Field(default=True, description="Require issued-at claim")
    claims: JWTClaimsConfig = Field(
        default_factory=JWTClaimsConfig, description="JWT claims mapping configuration"
    )
    jwks_cache_ttl_seconds: int = Field(
        default=3600,
        description="Time-to-live for cached JWKS responses",
    )
    jwks_cache_max_entries: int = Field(
        default=16,
        description="Maximum number of provider JWKS responses to cache",
    )


class LoggingConfig(BaseModel):
    """Logging configuration model."""

    level: str = Field(default="INFO", description="Logging level")
    format: Literal["json", "plain"] = Field(default="json", description="Log format")
    file: str = Field(default="logs/app.log", description="Log file path")
    max_size_mb: int = Field(default=10, description="Maximum log file size in MB")
    backup_count: int = Field(
        default=5, description="Number of backup log files to keep"
    )


class DatabaseConfig(BaseModel):
    """Database configuration model."""

    url: str = Field(
        default="postgresql+asyncpg://user:password@postgres:5432/app_db",
        description="Database connection URL",
    )
    owner_user: str = Field(default="appowner", description="Database owner username")
    user: str = Field(default="user", description="Database username")
    ro_user: str = Field(
        default="backupuser", description="Database read-only username"
    )
    app_db: str = Field(default="app_db", description="Database name")
    pool_size: int = Field(default=20, description="Connection pool size")
    environment_mode: str = Field(
        default="development", description="Environment mode: development or production"
    )
    max_overflow: int = Field(default=10, description="Maximum pool overflow")
    pool_timeout: int = Field(default=30, description="Pool timeout in seconds")
    pool_recycle: int = Field(default=1800, description="Pool recycle time in seconds")
    password_env_var: str | None = Field(
        default=None,
        description="Environment variable name containing database password",
    )

    password_file_path: str | None = Field(
        default=None,
        description="Path to file containing database password",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def password(self) -> str | None:
        """
        Get the database password from the appropriate source.
        1. If in development mode, try to parse from URL
        2. If in production mode, read from mounted secrets file specified
            by `password_file_path` or environment variable specified by `password_env_var`
        """
        password = None
        if self.environment_mode == "development" or self.environment_mode == "test":
            # In development mode, try to parse password from URL if present
            from sqlalchemy.engine import make_url

            url_obj = make_url(self.url)
            if url_obj.password:
                password = url_obj.password

        elif self.environment_mode == "production":
            # In production mode, read from file or environment variable

            logger.debug(
                "Attempting to read database password for production mode from environment variable {}",
                self.password_env_var,
            )
            if self.password_env_var:
                import os

                password = os.getenv(self.password_env_var)
                if password:
                    return password

            if not password and self.password_file_path:
                try:
                    with open(self.password_file_path, encoding="utf-8") as f:
                        password = f.read().strip()
                except Exception as e:
                    logger.error(
                        "Failed to read database password from file {}: {}",
                        self.password_file_path,
                        e,
                    )
                    raise
            if not password:
                logger.error(
                    "Database password not found in environment variable {} or file {}",
                    self.password_env_var,
                    self.password_file_path,
                )
                raise ValueError("Database password not provided in production mode")

        else:
            raise ValueError(
                "Invalid environment_mode; must be 'development', 'production', or 'test'"
            )
        return password

    @computed_field  # type: ignore[prop-decorator]
    @property
    def connection_string(self) -> str:
        """Construct the database connection string with password if provided."""
        from sqlalchemy.engine import make_url

        base_url = make_url(self.url)

        # If the URL already has a password (development mode), use it as-is
        if base_url.password:
            # If in production mode, emit a warning if password is hardcoded
            if self.environment_mode == "production":
                logger.warning(
                    "Database URL contains a password in production mode; "
                    "consider using a secrets file or environment variable."
                )

            if self.password != base_url.password:
                logger.warning(
                    "Database password from environment variable does not match the one in the URL. Using password from environment variable."
                )
                base_url = base_url.set(password=self.password)

            if self.app_db != base_url.database:
                logger.warning(
                    f"Database name '{self.app_db}' does not match the one in the URL '{base_url.database}'. Using '{self.app_db}'."
                )
                base_url = base_url.set(database=self.app_db)

            if self.user != base_url.username:
                logger.warning(
                    f"Database user '{self.user}' does not match the one in the URL '{base_url.username}'. Using '{self.user}'."
                )
                base_url = base_url.set(username=self.user)

            # URL-encode password to handle special characters
            from urllib.parse import quote_plus

            password_to_encode = base_url.password or ""
            encoded_password = quote_plus(password_to_encode)

            # Build base connection string
            conn_str = f"postgresql://{base_url.username}:{encoded_password}@{base_url.host}:{base_url.port}/{base_url.database}"

            # Add search_path=app ONLY for PostgreSQL in production mode
            if self.environment_mode == "production" and base_url.drivername.startswith(
                "postgresql"
            ):
                conn_str += "?options=-csearch_path%3Dapp"

            return conn_str

        # Otherwise, use the resolved password from the computed field and
        # the resolved user and database from the URL or config
        resolved_password = self.password
        # If the user or database is not set in the config, fall back to the URL
        resolved_user = self.user or base_url.username
        resolved_db = self.app_db or base_url.database

        if resolved_user != base_url.username and self.user:
            base_url = base_url.set(username=resolved_user)
        if resolved_db != base_url.database and self.app_db:
            base_url = base_url.set(database=resolved_db)

        if resolved_password:
            from urllib.parse import quote_plus

            # URL-encode password to handle special characters
            encoded_password = quote_plus(resolved_password)
            # Build the connection string manually with encoded password
            conn_str = f"postgresql://{resolved_user}:{encoded_password}@{base_url.host}:{base_url.port}/{resolved_db}"

            # Add search_path=app ONLY for PostgreSQL in production mode
            if self.environment_mode == "production" and base_url.drivername.startswith(
                "postgresql"
            ):
                conn_str += "?options=-csearch_path%3Dapp"

            return conn_str
        else:
            # Build connection string without password
            conn_str = f"postgresql://{base_url.username}@{base_url.host}:{base_url.port}/{base_url.database}"

            # Add search_path=app ONLY for PostgreSQL in production mode
            if self.environment_mode == "production" and base_url.drivername.startswith(
                "postgresql"
            ):
                conn_str += "?options=-csearch_path%3Dapp"

            return conn_str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sanitized_connection_string(self) -> str:
        """Get connection string with password masked for safe logging."""
        conn_str = self.connection_string
        if ":" in conn_str and "@" in conn_str:
            # Format: postgresql://user:PASSWORD@host:port/db
            # Split on LAST @ (password might contain @)
            parts = conn_str.rsplit("@", 1)
            if len(parts) == 2:
                prefix_parts = parts[0].split(":")
                if len(prefix_parts) >= 3:
                    # Reconstruct with masked password
                    scheme_and_user = ":".join(prefix_parts[:-1])  # postgresql://user
                    return f"{scheme_and_user}:****@{parts[1]}"
        return conn_str


class AppConfig(BaseModel):
    """Application configuration model."""

    environment: Literal["development", "production", "test"] = Field(
        default="development", description="Application environment"
    )
    host: str = Field(default="localhost", description="Application host")
    port: int = Field(default=8000, description="Application port")
    session_max_age: int = Field(
        default=3600, description="Session maximum age in seconds"
    )
    session_signing_secret: str | None = Field(
        default=None, description="Secret for signing session JWTs"
    )
    csrf_signing_secret: str | None = Field(
        default=None, description="Secret for signing CSRF tokens"
    )
    cors: CORSConfig = Field(
        default_factory=CORSConfig, description="CORS configuration"
    )

    @property
    def base_url(self) -> str:
        """Construct the base URL from host and port."""
        scheme = "https" if self.environment == "production" else "http"
        return f"{scheme}://{self.host}:{self.port}"


class SecurityConfig(BaseModel):
    """Security configuration for authentication and sessions."""

    # Cookie settings
    secure_cookies: bool = Field(
        default=True, description="Force secure cookies in production"
    )
    cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax", description="SameSite cookie attribute"
    )

    # CSRF protection
    csrf_header_name: str = Field(
        default="X-CSRF-Token", description="Header name for CSRF tokens"
    )
    csrf_token_max_age_hours: int = Field(
        default=24, description="Maximum age for CSRF tokens in hours"
    )

    # Client fingerprinting
    enable_client_fingerprinting: bool = Field(
        default=True, description="Enable client context binding for sessions"
    )
    strict_fingerprinting: bool = Field(
        default=True, description="Require exact fingerprint match"
    )

    # Session security
    auth_session_ttl_seconds: int = Field(
        default=600, description="Auth session TTL (10 minutes)"
    )
    single_use_auth_sessions: bool = Field(
        default=True, description="Invalidate auth sessions after successful callback"
    )


class ConfigData(BaseModel):
    """Root configuration model that matches the config.yaml structure."""

    rate_limiter: RateLimiterConfig = Field(
        default_factory=RateLimiterConfig, description="Rate limiter configuration"
    )
    temporal: TemporalConfig = Field(
        default_factory=TemporalConfig, description="Temporal configuration"
    )
    redis: RedisConfig = Field(
        default_factory=RedisConfig, description="Redis configuration"
    )
    oidc: OIDCConfig = Field(
        default_factory=OIDCConfig, description="OIDC configuration"
    )
    jwt: JWTConfig = Field(
        default_factory=JWTConfig, description="JWT validation configuration"
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig, description="Logging configuration"
    )
    database: DatabaseConfig = Field(
        default_factory=DatabaseConfig, description="Database configuration"
    )
    app: AppConfig = Field(
        default_factory=lambda: AppConfig(
            session_signing_secret=None, csrf_signing_secret=None
        ),
        description="Application configuration",
    )
    security: SecurityConfig = Field(
        default_factory=SecurityConfig, description="Security configuration"
    )
