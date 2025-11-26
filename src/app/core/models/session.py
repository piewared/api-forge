"""Enhanced session models with security features."""

import time
from typing import Any

from pydantic import BaseModel, Field


class AuthSession(BaseModel):
    """Temporary session for OIDC authorization flow with security enhancements."""

    id: str = Field(description="Session identifier")
    pkce_verifier: str = Field(description="PKCE code verifier")
    state: str = Field(description="CSRF state parameter")
    nonce: str = Field(description="OIDC nonce for replay protection")
    provider: str = Field(description="OIDC provider identifier")
    return_to: str = Field(description="Sanitized post-auth redirect URL")
    client_fingerprint_hash: str = Field(description="Client context fingerprint")
    created_at: int = Field(description="Creation timestamp")
    expires_at: int = Field(description="Expiration timestamp")
    used: bool = Field(default=False, description="Whether session has been used")

    @classmethod
    def create(
        cls,
        session_id: str,
        pkce_verifier: str,
        state: str,
        nonce: str,
        provider: str,
        return_to: str,
        client_fingerprint_hash: str,
        ttl_seconds: int = 600,
    ) -> "AuthSession":
        """Create a new auth session with timestamps."""
        now = int(time.time())
        return cls(
            id=session_id,
            pkce_verifier=pkce_verifier,
            state=state,
            nonce=nonce,
            provider=provider,
            return_to=return_to,
            client_fingerprint_hash=client_fingerprint_hash,
            created_at=now,
            expires_at=now + ttl_seconds,
        )

    def is_expired(self) -> bool:
        """Check if session is expired."""
        return time.time() > self.expires_at

    def mark_used(self) -> None:
        """Mark session as used (for single-use enforcement)."""
        self.used = True


class UserSession(BaseModel):
    """Persistent user session after successful authentication."""

    id: str = Field(description="Session identifier")
    user_id: str = Field(description="Internal user ID")
    provider: str = Field(description="OIDC provider identifier")
    refresh_token: str | None = Field(default=None, description="OAuth refresh token")
    access_token: str | None = Field(default=None, description="OAuth access token")
    access_token_expires_at: int | None = Field(
        default=None, description="Access token expiry"
    )
    client_fingerprint: str = Field(description="Client context fingerprint")
    created_at: int = Field(description="Creation timestamp")
    last_accessed_at: int = Field(description="Last access timestamp")
    expires_at: int = Field(description="Session expiration timestamp")

    @classmethod
    def create(
        cls,
        session_id: str,
        user_id: str,
        provider: str,
        client_fingerprint: str,
        refresh_token: str | None = None,
        access_token: str | None = None,
        access_token_expires_at: int | None = None,
        session_max_age: int = 3600,
    ) -> "UserSession":
        """Create a new user session with timestamps."""
        now = int(time.time())
        return cls(
            id=session_id,
            user_id=user_id,
            provider=provider,
            client_fingerprint=client_fingerprint,
            refresh_token=refresh_token,
            access_token=access_token,
            access_token_expires_at=access_token_expires_at,
            created_at=now,
            last_accessed_at=now,
            expires_at=now + session_max_age,
        )

    def is_expired(self) -> bool:
        """Check if session is expired."""
        return time.time() > self.expires_at

    def update_access(self) -> None:
        """Update last accessed time."""
        self.last_accessed_at = int(time.time())

    def rotate_session_id(self, new_session_id: str) -> None:
        """Rotate session ID for security."""
        self.id = new_session_id
        self.update_access()

    def update_tokens(
        self,
        access_token: str | None = None,
        refresh_token: str | None = None,
        access_token_expires_at: int | None = None,
    ) -> None:
        """Update token information."""
        if access_token is not None:
            self.access_token = access_token
        if refresh_token is not None:
            self.refresh_token = refresh_token
        if access_token_expires_at is not None:
            self.access_token_expires_at = access_token_expires_at
        self.update_access()


class TokenClaims(BaseModel):
    """Structured representation of JWT token claims."""

    # custom uid claim for user identification
    uid: str | None = Field(
        default=None, description="UID claim for user identification"
    )

    # Token metadata
    raw_token: str = Field(default="", description="Original JWT token")
    token_type: str = Field(default="id_token", description="Token type")

    # Standard OIDC claims
    issuer: str = Field(description="Issuer")
    subject: str = Field(description="Subject (user ID)")
    authorized_party: str | None = Field(
        default=None, description="Authorized party (azp)"
    )
    audience: str | list[str] = Field(description="Audience")
    expires_at: int = Field(description="Expiration time")
    issued_at: int = Field(description="Issued at")
    not_before: int | None = Field(default=None, description="Not before")
    jti: str | None = Field(
        default=None, description="JWT ID (unique token identifier)"
    )
    nonce: str | None = Field(default=None, description="Nonce for replay protection")

    # Common user claims
    email: str | None = Field(default=None, description="Email address")
    email_verified: bool = Field(default=False, description="Email verification status")
    name: str | None = Field(default=None, description="Full name")
    given_name: str | None = Field(default=None, description="First name")
    family_name: str | None = Field(default=None, description="Last name")
    preferred_username: str | None = Field(default=None, description="Username")

    # Authorization claims
    scope: str | None = Field(default=None, description="OAuth scopes")
    scopes: list[str] = Field(default_factory=list, description="Parsed OAuth scopes")
    roles: list[str] = Field(default_factory=list, description="User roles")
    groups: list[str] | None = Field(default=None, description="User groups")

    # Token binding
    at_hash: str | None = Field(default=None, description="Access token hash")
    c_hash: str | None = Field(default=None, description="Code hash")

    custom_claims: dict[str, Any] = Field(
        default_factory=dict, description="Custom or additional claims"
    )

    all_claims: dict[str, Any] = Field(
        default_factory=dict, description="All claims (including custom claims)"
    )

    @classmethod
    def from_jwt_payload(
        cls, payload: dict[str, Any], raw_token: str = "", token_type: str = "id_token"
    ) -> "TokenClaims":
        """Create TokenClaims from JWT payload dictionary."""
        # Map JWT claim names to model field names
        claim_mapping = {
            "iss": "issuer",
            "sub": "subject",
            "aud": "audience",
            "exp": "expires_at",
            "iat": "issued_at",
            "nbf": "not_before",
        }

        # Extract known fields with mapping
        known_fields = {
            field.alias or name
            for name, field in cls.model_fields.items()
            if name not in {"extra_claims", "custom_claims", "raw_token", "token_type"}
        }

        extracted: dict[str, Any] = {}
        extra = {}

        extracted["all_claims"] = payload.copy()

        for key, value in payload.items():
            # Check if this is a mapped claim
            mapped_field = claim_mapping.get(key, key)

            if mapped_field in known_fields:
                extracted[mapped_field] = value
            else:
                extra[key] = value

        # Set metadata
        extracted["raw_token"] = raw_token
        extracted["token_type"] = token_type
        extracted["extra_claims"] = extra
        extracted["custom_claims"] = extra  # Alias for backward compatibility

        return cls(**extracted)

    def validate_nonce(self, expected_nonce: str) -> bool:
        """Validate nonce claim against expected value."""
        return self.nonce == expected_nonce

    def validate_audience(self, expected_audiences: list[str]) -> bool:
        """Validate audience claim."""
        if isinstance(self.audience, str):
            return self.audience in expected_audiences
        elif isinstance(self.audience, list):
            return any(aud in expected_audiences for aud in self.audience)
        return False

    def is_expired(self, clock_skew: int = 60) -> bool:
        """Check if token is expired with clock skew tolerance."""
        return time.time() > self.expires_at + clock_skew

    def is_not_yet_valid(self, clock_skew: int = 60) -> bool:
        """Check if token is not yet valid with clock skew tolerance."""
        return (
            self.not_before is not None and time.time() < self.not_before - clock_skew
        )
