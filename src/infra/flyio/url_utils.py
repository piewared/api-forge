"""URL parsing utilities for Fly.io connection strings.

Provides robust extraction of host/port from Postgres URLs that may include
embedded credentials, extra status text from flyctl, or unusual formats.
"""

import re
from urllib.parse import urlparse


def extract_pg_host_port(url: str) -> tuple[str, str] | None:
    """Extract (host, port) from a postgres connection string.

    Handles:
    - Standard postgres:// or postgresql:// URLs
    - URLs with embedded credentials (special chars in password confuse urlparse)
    - Multi-line flyctl output where the URL appears on one line among status text
    - URLs without an explicit port (defaults to 5432)

    Args:
        url: A postgres connection string or output block containing one.

    Returns:
        ``(hostname, port_str)`` or ``None`` if extraction fails.
    """
    if not url:
        return None

    # If the input is multi-line (flyctl sometimes prepends status text), find
    # the line that actually looks like a postgres URL.
    for line in url.splitlines():
        stripped = line.strip()
        if re.match(r"postgres(?:ql)?://", stripped, re.IGNORECASE):
            url = stripped
            break
    else:
        url = url.strip()

    if not url:
        return None

    # Strategy 1 — standard urlparse (works for most well-formed URLs)
    try:
        parsed = urlparse(url)
        if parsed.hostname:
            return parsed.hostname, str(parsed.port or 5432)
    except Exception:
        pass

    # Strategy 2 — regex fallback: handles special characters in passwords that
    # trip up urlparse by looking for host:port after @ or //
    match = re.search(r"(?:@|//)([a-zA-Z0-9._-]+):(\d+)", url)
    if match:
        return match.group(1), match.group(2)

    # Strategy 3 — host without port (after @ or //)
    match = re.search(r"(?:@|//)([a-zA-Z0-9._-]+)/", url)
    if match:
        return match.group(1), "5432"

    return None
