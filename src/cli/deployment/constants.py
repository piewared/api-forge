"""Shared deployment constants."""

from pathlib import Path

DEFAULT_DATA_SUBDIRS = [
    Path("postgres"),
    Path("postgres-backups"),
    Path("postgres-ssl"),
    Path("redis"),
    Path("redis-backups"),
    Path("app-logs"),
    Path("temporal-certs"),
]
