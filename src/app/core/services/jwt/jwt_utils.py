import base64
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final, cast

from cachetools.func import lru_cache  # type: ignore[import-untyped]
from fastapi import HTTPException
from loguru import logger

from src.app.core.models.session import TokenClaims
from src.app.runtime.config.config_data import OIDCProviderConfig
from src.app.runtime.context import get_config

# ---------------- tunables ----------------
MAX_JWT_CHARS: Final = 4096
MAX_SEGMENT_CHARS: Final = 4096
MAX_HEADER_BYTES: Final = 8 * 1024
MAX_PAYLOAD_BYTES: Final = 64 * 1024
_ALLOWED: Final = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_."
)  # no '='


# --------------- one-pass prefilter ---------------
def _prefilter_compact_jwt(token: str) -> tuple[str, str, str]:
    if not token or len(token) > MAX_JWT_CHARS:
        raise HTTPException(status_code=401, detail="Invalid JWT size")
    first = second = -1
    for i, ch in enumerate(token):
        if ch not in _ALLOWED:
            raise HTTPException(status_code=401, detail="Invalid JWT characters")
        if ch == ".":
            if first < 0:
                first = i
            elif second < 0:
                second = i
            else:  # third dot
                raise HTTPException(status_code=401, detail="Invalid JWT format")
    # require exactly two dots and non-empty segments
    if first <= 0 or second - first <= 1 or second >= len(token) - 1:
        raise HTTPException(status_code=401, detail="Invalid JWT format")
    h, p, s = token[:first], token[first + 1 : second], token[second + 1 :]
    if (
        len(h) > MAX_SEGMENT_CHARS
        or len(p) > MAX_SEGMENT_CHARS
        or len(s) > MAX_SEGMENT_CHARS
    ):
        raise HTTPException(status_code=401, detail="Invalid JWT segment size")
    return h, p, s


def _b64url_decode_unpadded(seg: str, what: str, max_bytes: int) -> bytes:
    pad = (-len(seg)) % 4
    try:
        raw = base64.urlsafe_b64decode((seg + "=" * pad).encode("ascii"))
    except Exception as e:
        raise HTTPException(
            status_code=401, detail=f"Invalid base64url in {what}"
        ) from e
    if len(raw) > max_bytes:
        raise HTTPException(status_code=401, detail=f"{what} too large")
    return raw


def _decode_json_object(raw: bytes, what: str) -> dict[str, Any]:
    try:
        obj = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=401, detail=f"Non-UTF8 {what}") from e
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=401, detail=f"Invalid JSON in {what}") from e
    if not isinstance(obj, dict):
        raise HTTPException(status_code=401, detail=f"{what} must be a JSON object")
    return obj


@dataclass(frozen=True)
class JwtPreview:
    header: dict[str, Any]
    claims: dict[str, Any]
    alg: str | None
    kid: str | None
    iss: str | None


def preview_jwt(token: str) -> JwtPreview:
    """Split and decode header+payload exactly once."""
    h_seg, p_seg, _ = _prefilter_compact_jwt(token)
    h_raw = _b64url_decode_unpadded(h_seg, "JWT header", MAX_HEADER_BYTES)
    p_raw = _b64url_decode_unpadded(p_seg, "JWT payload", MAX_PAYLOAD_BYTES)
    header = _decode_json_object(h_raw, "JWT header")
    claims = _decode_json_object(p_raw, "JWT payload")
    iss = claims.get("iss")
    if iss and isinstance(iss, str):
        iss = iss.rstrip("/")  # normalize
    else:
        iss = None

    return JwtPreview(
        header=header,
        claims=claims,
        alg=header.get("alg"),
        kid=header.get("kid"),
        iss=iss,
    )


@lru_cache(maxsize=24)
def lookup_config_by_issuer(issuer: str) -> OIDCProviderConfig | None:
    """Look up OIDC provider config by issuer URL."""
    config = get_config()

    for p in config.oidc.providers.values():
        iss = getattr(p, "issuer", None)
        if isinstance(iss, str) and iss.rstrip("/") == issuer.rstrip("/"):
            return p
    return None


def extract_uid(claims: dict[str, Any]) -> str:
    main_config = get_config()
    uid_claim = main_config.jwt.claims.user_id
    if uid_claim and uid_claim in claims:
        if not isinstance(claims[uid_claim], str):
            raise HTTPException(status_code=401, detail="Invalid UID claim type")
        return cast(str, claims[uid_claim])
    return f"{claims.get('iss')}|{claims.get('sub')}"


def extract_scopes(claims: dict[str, Any]) -> list[str]:
    """Extract scopes from JWT claims, preserving order.

    Scopes can be in various claims: 'scope' (space-separated), 'scp' (string or array),
    or 'scopes' (array). Returns as a list with deduplication, preserving first occurrence order.
    """
    seen = set()
    scopes = []

    # Helper to add scopes while preserving order and deduplication
    def add_scope_items(items: Iterable[str]) -> None:
        for item in items:
            if item not in seen:
                seen.add(item)
                scopes.append(item)

    # 'scope' claim (space-separated string)
    if "scope" in claims:
        add_scope_items(str(claims["scope"]).split())

    # 'scp' claim (string or array)
    if "scp" in claims:
        value = claims["scp"]
        if isinstance(value, str):
            add_scope_items(value.split())
        elif isinstance(value, (list, tuple)):
            add_scope_items(value)

    # 'scopes' claim (array)
    if "scopes" in claims and isinstance(claims["scopes"], (list, tuple)):
        add_scope_items(claims["scopes"])

    return scopes


def extract_roles(claims: dict[str, Any]) -> list[str]:
    """Extract roles from JWT claims.

    Roles can be in various claims and nested structures.
    """
    roles: list[str] = []

    # Check for common role claims (both singular and plural)
    for role_claim in ["role", "roles", "groups", "authorities"]:
        value = claims.get(role_claim)
        if value:
            if isinstance(value, list):
                print("Extracted roles from list:", value)
                roles.extend(value)
            elif isinstance(value, str):
                # Handle space-separated roles string
                roles.extend(value.split())
            else:
                roles.append(str(value))

    # Check for Auth0 style roles (e.g., in app_metadata or custom claims)
    app_metadata = claims.get("app_metadata", {})
    if isinstance(app_metadata, dict) and "roles" in app_metadata:
        auth0_roles = app_metadata["roles"]
        if isinstance(auth0_roles, list):
            roles.extend(auth0_roles)

    # Check for Keycloak realm roles
    if "realm_access" in claims and "roles" in claims["realm_access"]:
        keycloak_roles = claims["realm_access"]["roles"]
        if isinstance(keycloak_roles, list):
            roles.extend(keycloak_roles)

    # Check for custom namespace roles (Auth0 custom claims pattern)
    for key, value in claims.items():
        if key != "roles" and "roles" in key.lower() and isinstance(value, list):
            roles.extend(value)
    return roles


def create_token_claims(
    token: str,
    claims: dict[str, Any],
    token_type: str = "id_token",
    issuer: str | None = None,
) -> TokenClaims:
    """Create TokenClaims instance from verified JWT claims.

    Args:
        token: The raw JWT token
        claims: Verified JWT claims
        token_type: Type of token (id_token, access_token)
        issuer: Fallback issuer if not present in claims (mainly for userinfo endpoint responses)

    Returns:
        TokenClaims instance with parsed claims
    """
    # Secure defaults for exp (expiration) and iat (issued at):
    # - iat: current time (int(time.time()))
    # - exp: current time + reasonable lifetime (e.g., 3600 seconds = 1 hour)
    # If claims do not provide these, set defaults.

    now = int(time.time())

    # Make a copy to avoid modifying the original claims dict
    remaining_claims = claims.copy()

    logger.debug(
        "Creating TokenClaims for issuer=%s subject=%s token_type=%s (claims=%d)",
        remaining_claims.get("iss"),
        remaining_claims.get("sub"),
        token_type,
        len(remaining_claims),
    )

    uid = extract_uid(remaining_claims)

    # Extract standard JWT claims (pop them as we parse)
    expires_at = remaining_claims.pop("exp", now + 3600)  # Default: 1 hour from now
    issued_at = remaining_claims.pop("iat", now)  # Default: now
    not_before = remaining_claims.pop("nbf", None)
    subject = remaining_claims.pop("sub", "")
    audience = remaining_claims.pop("aud", [])
    azp = remaining_claims.pop("azp", None)
    token_issuer = remaining_claims.pop("iss", None) or issuer or ""

    # Extract OIDC claims that we use
    nonce = remaining_claims.pop("nonce", None)
    jti = remaining_claims.pop("jti", None)

    # Extract profile claims that we use
    email = remaining_claims.pop("email", None)
    email_verified = remaining_claims.pop("email_verified", False)
    name = remaining_claims.pop("name", None)
    given_name = remaining_claims.pop("given_name", None) or remaining_claims.pop(
        "first_name", None
    )
    family_name = remaining_claims.pop("family_name", None) or remaining_claims.pop(
        "last_name", None
    )

    # Extract scopes and roles (these functions will handle multiple claim variations)
    scopes = extract_scopes(claims)  # Use original claims for extraction
    roles = extract_roles(claims)  # Use original claims for extraction

    # Remove only the claims that we've explicitly extracted and mapped to TokenClaims fields
    # This ensures we don't lose any information - all unmapped claims stay in custom_claims

    # Remove scope/role claims that we've processed into dedicated fields
    # Note: We need to be careful here since extract_scopes/extract_roles handle multiple variations
    for scope_claim in ["scope", "scopes", "scp"]:
        remaining_claims.pop(scope_claim, None)
    for role_claim in ["role", "roles", "groups", "authorities"]:
        remaining_claims.pop(role_claim, None)

    # Remove nested structures that we've processed for roles
    # Only remove these if they were actually used for role extraction
    if "realm_access" in remaining_claims and "roles" in remaining_claims.get(
        "realm_access", {}
    ):
        remaining_claims.pop("realm_access", None)
    if "app_metadata" in remaining_claims and "roles" in remaining_claims.get(
        "app_metadata", {}
    ):
        remaining_claims.pop("app_metadata", None)

    return TokenClaims(
        raw_token=token,
        uid=uid,
        email_verified=email_verified,
        all_claims=claims.copy(),
        issuer=token_issuer,
        subject=subject,
        audience=audience,
        authorized_party=azp,
        expires_at=expires_at,
        issued_at=issued_at,
        not_before=not_before,
        nonce=nonce,
        jti=jti,
        token_type=token_type,
        scope=" ".join(scopes),
        scopes=list(scopes),
        roles=roles,
        email=email,
        name=name,
        given_name=given_name,
        family_name=family_name,
        custom_claims=remaining_claims,  # Only truly custom claims remain
    )
