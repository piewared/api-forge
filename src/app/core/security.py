"""Security utilities for OIDC authentication flow."""

import base64
import hashlib
import hmac
import secrets
import time

from fastapi import Request

from src.app.runtime.context import get_config


def generate_secure_token(length: int = 32) -> str:
    """Generate a cryptographically secure random token.

    Args:
        length: Number of random bytes to generate (default 32)

    Returns:
        URL-safe base64 encoded token
    """
    return (
        base64.urlsafe_b64encode(secrets.token_bytes(length))
        .decode("utf-8")
        .rstrip("=")
    )


def generate_nonce() -> str:
    """Generate a cryptographically secure nonce for OIDC flow.

    Returns:
        URL-safe base64 encoded nonce (256 bits of entropy)
    """
    return generate_secure_token(32)


def generate_state() -> str:
    """Generate a cryptographically secure state parameter for CSRF protection.

    Returns:
        URL-safe base64 encoded state (256 bits of entropy)
    """
    return generate_secure_token(32)


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge pair.

    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    # Generate random code verifier (43-128 characters)
    code_verifier = generate_secure_token(32)

    # Create SHA256 challenge
    challenge_bytes = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = (
        base64.urlsafe_b64encode(challenge_bytes).decode("utf-8").rstrip("=")
    )

    return code_verifier, code_challenge


def generate_csrf_token(session_id: str, timestamp: int | None = None) -> str:
    """Generate CSRF token bound to session and time.

    Args:
        session_id: Session identifier to bind token to
        timestamp: Optional timestamp (defaults to current hour)

    Returns:
        HMAC-based CSRF token
    """
    if timestamp is None:
        timestamp = int(time.time() // 3600)  # Hour-based for reasonable lifetime

    config = get_config()
    if not config.app.csrf_signing_secret:
        raise ValueError("CSRF_SIGNING_SECRET must be set to generate CSRF tokens")

    secret_key = config.app.csrf_signing_secret.encode()

    message = f"{session_id}:{timestamp}"
    csrf_token = hmac.new(secret_key, message.encode(), hashlib.sha256).hexdigest()

    # Include timestamp for verification
    return f"{timestamp}:{csrf_token}"


def validate_csrf_token(
    session_id: str, csrf_token: str | None, max_age_hours: int = 12
) -> bool:
    """Validate CSRF token for session.

    Args:
        session_id: Session identifier
        csrf_token: CSRF token to validate
        max_age_hours: Maximum age of token in hours

    Returns:
        True if valid, False otherwise
    """
    if not csrf_token:
        return False

    try:
        # Parse timestamp and token
        parts = csrf_token.split(":", 1)
        if len(parts) != 2:
            return False

        token_timestamp, token_value = parts
        timestamp = int(token_timestamp)

        # Check token age
        current_hour = int(time.time() // 3600)
        if current_hour - timestamp > max_age_hours:
            return False

        # Generate expected token
        expected_token = generate_csrf_token(session_id, timestamp)
        expected_value = expected_token.split(":", 1)[1]

        # Constant-time comparison
        return hmac.compare_digest(expected_value, token_value)

    except (ValueError, IndexError):
        return False


def sanitize_return_url(
    return_to: str | None, allowed_hosts: list[str] | None = None
) -> str:
    """Sanitize return URL to prevent open redirects.

    Args:
        return_to: User-provided return URL
        allowed_hosts: Optional list of allowed hosts for absolute URLs

    Returns:
        Sanitized return URL (relative path or allowed absolute URL)
    """
    if not return_to:
        return "/"

    return_to = return_to.strip()

    # Allow relative paths starting with /
    if return_to.startswith("/") and not return_to.startswith("//"):
        # Ensure it's a valid path (no control characters)
        if all(ord(c) >= 32 for c in return_to):
            return return_to

    # Check absolute URLs against allowlist
    if allowed_hosts and (
        return_to.startswith("http://") or return_to.startswith("https://")
    ):
        try:
            from urllib.parse import urlparse

            parsed = urlparse(return_to)
            if parsed.hostname in allowed_hosts:
                return return_to
        except Exception:
            pass

    # Default to safe fallback
    return "/"


def hash_client_fingerprint(
    user_agent: str | None, client_ip: str | None = None
) -> str:
    """Create a stable fingerprint for client context binding.

    Args:
        user_agent: Client User-Agent header
        client_ip: Optional client IP (be careful with proxies)

    Returns:
        SHA256 hash of client characteristics
    """
    components = []

    if user_agent:
        components.append(user_agent.strip())

    if client_ip:
        components.append(client_ip.strip())

    if not components:
        # Fallback for missing data
        components.append("unknown-client")

    fingerprint_data = "|".join(components)
    return hashlib.sha256(fingerprint_data.encode("utf-8")).hexdigest()


def extract_client_fingerprint(request: Request) -> str:
    """Extract and hash client fingerprint from FastAPI request.

    Args:
        request: FastAPI Request object

    Returns:
        SHA256 hash of client characteristics
    """
    user_agent = request.headers.get("user-agent")

    # Try to get real client IP, accounting for proxies
    client_ip = None

    # Check for forwarded headers (in order of preference)
    forwarded_headers = [
        "x-forwarded-for",
        "x-real-ip",
        "cf-connecting-ip",  # Cloudflare
        "x-forwarded-host",
    ]

    for header in forwarded_headers:
        value = request.headers.get(header)
        if value:
            # Take first IP if comma-separated list
            client_ip = value.split(",")[0].strip()
            break

    # Fallback to direct client IP
    if not client_ip and hasattr(request, "client") and request.client:
        client_ip = request.client.host

    print(
        f"extract_client_fingerprint called with user_agent: {user_agent}, client_ip: {client_ip}"
    )
    return hash_client_fingerprint(user_agent, client_ip)


def validate_client_fingerprint(
    stored_fingerprint: str,
    current_user_agent: str | None,
    current_client_ip: str | None = None,
    strict: bool = True,
) -> bool:
    """Validate client fingerprint for session binding.

    Args:
        stored_fingerprint: Previously stored fingerprint
        current_user_agent: Current User-Agent header
        current_client_ip: Current client IP
        strict: If True, exact match required. If False, allows some variation.

    Returns:
        True if fingerprint matches within tolerance
    """
    current_fingerprint = hash_client_fingerprint(current_user_agent, current_client_ip)

    if strict:
        return hmac.compare_digest(stored_fingerprint, current_fingerprint)
    else:
        # For non-strict mode, we could implement fuzzy matching
        # For now, just exact match
        return hmac.compare_digest(stored_fingerprint, current_fingerprint)
