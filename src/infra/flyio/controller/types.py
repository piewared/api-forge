"""Data types for Fly.io controller responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CommandResult:
    """Result of a command execution."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


@dataclass
class ManagedPostgresInfo:
    """Information about a Fly Managed Postgres cluster."""

    id: str
    name: str
    region: str
    plan: str
    status: str
    created_at: str = ""
    connection_string: str | None = None


@dataclass
class FlyAppInfo:
    """Information about a Fly.io application."""

    name: str
    organization: str
    status: str
    hostname: str = ""


def parse_app_info(data: dict[str, Any]) -> FlyAppInfo:
    """Parse a FlyAppInfo from a flyctl JSON response dict."""
    org_data = data.get("Organization", {})
    org_slug = org_data.get("Slug", "") if isinstance(org_data, dict) else ""
    return FlyAppInfo(
        name=data.get("Name", ""),
        organization=org_slug,
        status=data.get("Status", ""),
        hostname=data.get("Hostname", ""),
    )


@dataclass
class BackupInfo:
    """Information about a Fly Managed Postgres backup."""

    id: str
    status: str
    created_at: str
    size_bytes: int = 0
