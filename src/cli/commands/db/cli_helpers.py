"""Shared command-body helpers for db CLI commands across environments.

Each environment (prod / k8s / fly) defines its own set of typer commands
(``init`` / ``verify`` / ``sync`` / ``backup`` / ``reset`` / ``status`` /
``migrate``). The actual workflow logic lives in ``db.workflows``; only the
typer-wiring boilerplate (header label + exit-on-failure + small UX bits)
differed between environments. These helpers consolidate that boilerplate
so each command becomes a one-liner.

The typer ``@app.command`` decorators must remain in each environment's
file (they hook into typer's introspection at import time), but the
function bodies should not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from src.cli.shared.console import console

from .runtime import DbRuntime
from .workflows import (
    run_backup,
    run_init,
    run_migrate,
    run_reset,
    run_status,
    run_sync,
    run_verify,
)


def _exit_on_failure(success: bool, retry_hint: str | None = None) -> None:
    """Raise ``typer.Exit(1)`` when a workflow returned False.

    If ``retry_hint`` is provided, the user-facing hint is printed before
    exiting so the next step is obvious.
    """
    if success:
        return
    if retry_hint:
        console.info(retry_hint)
    raise typer.Exit(1)


def execute_init(runtime: DbRuntime, *, label: str) -> None:
    """Initialize roles and schema for the given environment."""
    console.print_header(f"Initializing PostgreSQL Database ({label})")
    _exit_on_failure(run_init(runtime))


def execute_verify(
    runtime: DbRuntime,
    *,
    label: str,
    superuser_mode: bool,
    retry_hint: str | None = None,
) -> None:
    """Verify roles, schema ownership, and privileges."""
    console.print_header(f"Verifying PostgreSQL Configuration ({label})")
    _exit_on_failure(
        run_verify(runtime, superuser_mode=superuser_mode), retry_hint=retry_hint
    )


def execute_sync(runtime: DbRuntime, *, label: str) -> None:
    """Synchronize role passwords from secrets to the database."""
    console.print_header(f"Synchronizing PostgreSQL Passwords ({label})")
    _exit_on_failure(run_sync(runtime))


def execute_backup(
    runtime: DbRuntime,
    *,
    label: str,
    output_dir: Path | None,
    superuser_mode: bool,
) -> None:
    """Take a pg_dump backup, exiting non-zero on failure."""
    console.print_header(f"Creating PostgreSQL Backup ({label})")
    backup_dir = output_dir or Path("./data/postgres-backups")
    success, result = run_backup(
        runtime, output_dir=backup_dir, superuser_mode=superuser_mode
    )
    if not success:
        console.error(f"Backup failed: {result}")
        raise typer.Exit(1)
    console.print(f"\n[bold green]🎉 Backup created: {result}[/bold green]")


def execute_reset(
    runtime: DbRuntime,
    *,
    label: str,
    include_temporal: bool,
    superuser_mode: bool,
    retry_command: str,
) -> None:
    """Drop application databases / roles / schemas and exit non-zero on failure."""
    console.print_header(f"Resetting PostgreSQL Database ({label})")
    _exit_on_failure(
        run_reset(
            runtime,
            include_temporal=include_temporal,
            superuser_mode=superuser_mode,
        )
    )
    console.print("\n[bold green]🎉 PostgreSQL database reset complete![/bold green]")
    console.print("\n[dim]To re-initialize:[/dim]")
    console.print(f"  Run '{retry_command}'")


def execute_status(runtime: DbRuntime, *, label: str, superuser_mode: bool) -> None:
    """Print health and performance metrics."""
    console.print_header(f"PostgreSQL Health & Performance ({label})")
    run_status(runtime, superuser_mode=superuser_mode)


def execute_migrate(runtime: DbRuntime, /, **migrate_kwargs: Any) -> None:
    """Run an Alembic migration command. Kwargs are forwarded verbatim to
    ``run_migrate`` — environments differ only in which runtime they pass in."""
    run_migrate(runtime, **migrate_kwargs)
