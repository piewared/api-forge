import time
from typing import Any

from authlib.jose import JoseError, jwt
from fastapi import HTTPException
from loguru import logger

from src.app.runtime.config.config_data import ConfigData
from src.app.runtime.context import get_config


class JwtGeneratorService:
    """Service for generating JWT tokens for API authentication."""

    def generate_jwt(
        self,
        subject: str,
        claims: dict[str, Any] | None = None,
        expires_in_seconds: int = 3600,
        valid_after_seconds: int = 0,
        issuer: str | None = None,
        audience: str | list[str] | None = None,
        algorithm: str = "HS256",
        include_jti: bool = True,
        secret: str | None = None,
        kid: str | None = None,
    ) -> str:
        """Generate a signed JWT token for API authentication using authlib.

        Args:
            subject: Subject (sub) claim - typically user ID
            claims: Additional claims to include in the token
            expires_in_seconds: Token lifetime in seconds (default: 1 hour)
            valid_after_seconds: Time in seconds before the token is valid (default: 0)
            issuer: Issuer (iss) claim (defaults to config issuer)
            audience: Audience (aud) claim (defaults to config audiences)
            algorithm: Signing algorithm (default: HS256)
            include_jti: Whether to include a unique JWT ID claim (default: True)
            secret: Optional secret key for signing. If None, will use config secret.
            kid: Optional Key ID for JWT header (required for JWKS verification)

        Returns:
            Signed JWT token string

        Raises:
            HTTPException: If configuration is missing or invalid
        """
        from authlib.common.security import generate_token

        config: ConfigData = get_config()

        # If issuer is not provided, use default from config
        if not issuer:
            issuer = config.jwt.gen_issuer

        # Get signing secret
        if not secret:
            secret = config.app.session_signing_secret

        if not secret:
            raise HTTPException(
                status_code=500, detail="JWT signing secret not configured"
            )

        # Validate algorithm
        if algorithm not in config.jwt.allowed_algorithms:
            logger.debug(
                f"Attempted to use disallowed algorithm: {algorithm}, only {config.jwt.allowed_algorithms} are allowed"
            )
            raise HTTPException(
                status_code=500, detail=f"Algorithm {algorithm} not allowed"
            )

        # Build payload with proper time handling
        now = int(time.time())

        # Build the audience claim. If audience is not specified, use config audiences
        aud = audience or config.jwt.audiences or ["api"]

        # If audience is a list with multiple entries, make sure to include an authorized party (azp) claim
        if isinstance(aud, list) and len(aud) > 1:
            if claims is None:
                claims = {}
            claims["azp"] = aud[0]  # Authorized party is the first audience

        payload = {
            "iss": issuer or f"api-{config.app.environment}",
            "sub": subject,
            "aud": aud,
            "exp": now + expires_in_seconds,
            "iat": now,
            "nbf": now + valid_after_seconds,
        }

        # Add unique JWT ID for token tracking/revocation if requested
        if include_jti:
            payload["jti"] = generate_token(16)  # Use authlib's secure token generator

        # Add custom claims (filter out standard JWT claims to avoid conflicts)
        if claims:
            filtered_claims = {
                k: v
                for k, v in claims.items()
                if k not in {"iss", "sub", "aud", "exp", "iat", "nbf", "jti"}
            }
            payload.update(filtered_claims)

        try:
            # Use authlib's JWT encoding with proper header
            header = {"alg": algorithm, "typ": "JWT"}

            # Add Key ID to header if provided (required for JWKS verification)
            if kid:
                header["kid"] = kid

            # Use string key for consistency with type hints
            secret_key = secret if isinstance(secret, str) else secret.decode()
            token = jwt.encode(header, payload, secret_key)

            # authlib returns bytes, decode to string
            return token.decode() if isinstance(token, bytes) else token

        except JoseError as e:
            raise HTTPException(
                status_code=500, detail=f"JWT encoding failed: {str(e)}"
            ) from e
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to generate JWT: {str(e)}"
            ) from e

    def generate_access_token(
        self,
        user_id: str,
        scopes: list[str] | None = None,
        roles: list[str] | None = None,
        expires_in_seconds: int = 3600,
        issuer: str | None = None,
        audience: str | list[str] | None = None,
        algorithm: str = "HS256",
        include_jti: bool = True,
        secret: str | None = None,
        kid: str | None = None,
        **extra_claims: Any,
    ) -> str:
        """Generate an access token JWT for API authentication.

        Args:
            user_id: User identifier for the subject claim
            scopes: User scopes/permissions
            roles: User roles
            expires_in_seconds: Token lifetime in seconds (default: 1 hour)
            issuer: Issuer (iss) claim (defaults to config issuer)
            audience: Audience (aud) claim (defaults to config audiences)
            algorithm: Signing algorithm (default: HS256)
            include_jti: Whether to include a unique JWT ID claim (default: True)
            secret: Optional secret key for signing. If None, will use config secret.
            kid: Optional Key ID for JWT header (required for JWKS verification)
            **extra_claims: Additional claims to include

        Returns:
            Signed access token JWT

        Example:
            token = generate_access_token(
                user_id="user123",
                scopes=["read:posts", "write:comments"],
                roles=["user", "moderator"],
                issuer="my-api",
                audience=["api", "mobile-app"],
                algorithm="HS256",
                kid="key-1",
                email="user@example.com"
            )
        """
        claims: dict[str, str | list[str]] = {}

        if scopes:
            claims["scope"] = " ".join(scopes)
            claims["scopes"] = scopes

        if roles:
            claims["roles"] = roles

        # Add any extra claims
        claims.update(extra_claims)

        return self.generate_jwt(
            subject=user_id,
            claims=claims,
            expires_in_seconds=expires_in_seconds,
            issuer=issuer,
            audience=audience,
            algorithm=algorithm,
            include_jti=include_jti,
            secret=secret,
            kid=kid,
        )

    def generate_id_token(
        self,
        user_id: str,
        email: str | None = None,
        name: str | None = None,
        given_name: str | None = None,
        family_name: str | None = None,
        nonce: str | None = None,
        expires_in_seconds: int = 3600,
        issuer: str | None = None,
        audience: str | list[str] | None = None,
        algorithm: str = "HS256",
        include_jti: bool = True,
        secret: str | None = None,
        kid: str | None = None,
        **extra_claims: Any,
    ) -> str:
        """Generate an ID token JWT for user identification.

        Args:
            user_id: User identifier for the subject claim
            email: User email
            name: Full name
            given_name: First name
            family_name: Last name
            nonce: OIDC nonce for replay protection
            expires_in_seconds: Token lifetime in seconds (default: 1 hour)
            issuer: Issuer (iss) claim (defaults to config issuer)
            audience: Audience (aud) claim (defaults to config audiences)
            algorithm: Signing algorithm (default: HS256)
            include_jti: Whether to include a unique JWT ID claim (default: True)
            secret: Optional secret key for signing. If None, will use config secret.
            kid: Optional Key ID for JWT header (required for JWKS verification)
            **extra_claims: Additional claims to include

        Returns:
            Signed ID token JWT

        Example:
            id_token = generate_id_token(
                user_id="user123",
                email="user@example.com",
                given_name="John",
                family_name="Doe",
                nonce="abc123",
                issuer="auth-server",
                audience="client-app",
                kid="key-1"
            )
        """
        claims: dict[str, str | bool] = {}

        if email:
            claims["email"] = email
            claims["email_verified"] = True  # Assume verified if provided

        if name:
            claims["name"] = name

        if given_name:
            claims["given_name"] = given_name

        if family_name:
            claims["family_name"] = family_name

        if nonce:
            claims["nonce"] = nonce

        # Add any extra claims
        claims.update(extra_claims)

        return self.generate_jwt(
            subject=user_id,
            claims=claims,
            expires_in_seconds=expires_in_seconds,
            issuer=issuer,
            audience=audience,
            algorithm=algorithm,
            include_jti=include_jti,
            secret=secret,
            kid=kid,
        )

    def generate_refresh_token(
        self,
        user_id: str,
        client_id: str | None = None,
        expires_in_seconds: int = 7 * 24 * 3600,  # 7 days
        issuer: str | None = None,
        audience: str | list[str] | None = None,
        algorithm: str = "HS256",
        include_jti: bool = True,
        secret: str | None = None,
        kid: str | None = None,
        **extra_claims: Any,
    ) -> str:
        """Generate a refresh token JWT for token renewal.

        Args:
            user_id: User identifier for the subject claim
            client_id: Optional client identifier
            expires_in_seconds: Token lifetime in seconds (default: 7 days)
            issuer: Issuer (iss) claim (defaults to config issuer)
            audience: Audience (aud) claim (defaults to config audiences)
            algorithm: Signing algorithm (default: HS256)
            include_jti: Whether to include a unique JWT ID claim (default: True)
            secret: Optional secret key for signing. If None, will use config secret.
            kid: Optional Key ID for JWT header (required for JWKS verification)
            **extra_claims: Additional claims to include

        Returns:
            Signed refresh token JWT

        Example:
            refresh_token = generate_refresh_token(
                user_id="user123",
                client_id="webapp",
                issuer="auth-server",
                audience="refresh-service",
                kid="key-1",
                session_id="session456"
            )
        """
        claims = {"token_type": "refresh"}

        if client_id:
            claims["client_id"] = client_id

        # Add any extra claims
        claims.update(extra_claims)

        return self.generate_jwt(
            subject=user_id,
            claims=claims,
            expires_in_seconds=expires_in_seconds,
            issuer=issuer,
            audience=audience,
            algorithm=algorithm,
            include_jti=include_jti,
            secret=secret,
            kid=kid,
        )
