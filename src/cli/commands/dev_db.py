"""Database management for the local development environment.

This module provides db subcommands under 'dev'. Unlike ``prod db`` /
``k8s db`` / ``fly db``, it does not manage roles, credentials, or backups:
the development database is whatever ``config.yaml`` resolves for the
``development`` environment and is expected to be disposable. What it does
provide is the schema-migration surface, so a developer never has to invoke
Alembic with a hand-built DATABASE_URL.
"""

from typing import Annotated

import typer

from src.cli.commands.db.local_url import get_dev_database_url
from src.cli.shared.console import console, with_error_handling
from src.infra.postgres.migrations import run_migration

dev_db_app = typer.Typer(
    name="db",
    help="Development database schema management.",
    no_args_is_help=True,
)


@dev_db_app.command()
@with_error_handling
def url() -> None:
    """Show the resolved development database URL.

    The password is masked. Use this to confirm which database the migration
    commands below will act on.

    Examples:
        uv run api-forge-cli dev db url
    """
    from sqlalchemy.engine import make_url

    # str() on a SQLAlchemy URL masks the password, which is what we want here.
    console.print(f"[cyan]{make_url(get_dev_database_url())}[/cyan]")


@dev_db_app.command()
@with_error_handling
def migrate(
    action: Annotated[
        str,
        typer.Argument(
            help=(
                "Migration action: upgrade, downgrade, current, history, revision, "
                "heads, merge, show, stamp"
            )
        ),
    ],
    revision: Annotated[
        str | None,
        typer.Argument(
            help="Target revision (for downgrade) or message (for revision)"
        ),
    ] = None,
    message: Annotated[
        str | None,
        typer.Option(
            "--message",
            "-m",
            help=(
                "Optional message (used by revision and merge). If omitted, the "
                "second positional argument is used as the message."
            ),
        ),
    ] = None,
    merge_revisions: Annotated[
        list[str] | None,
        typer.Option(
            "--merge-revision",
            "-r",
            help=(
                "Revision(s) to merge (for merge). Can be provided multiple times. "
                "If omitted, merges all current heads."
            ),
        ),
    ] = None,
    purge: Annotated[
        bool,
        typer.Option(
            "--purge",
            help=(
                "For stamp only: purge the version table before stamping. "
                "Use with extreme care."
            ),
        ),
    ] = False,
    autogenerate: Annotated[
        bool,
        typer.Option(
            "--autogenerate/--no-autogenerate",
            help="Autogenerate migration from model changes (for revision)",
        ),
    ] = True,
    sql: Annotated[
        bool,
        typer.Option(
            "--sql",
            help="Generate SQL output instead of running migration",
        ),
    ] = False,
) -> None:
    """Manage development database schema migrations with Alembic.

    Actions:
        upgrade [revision]   - Apply migrations up to revision (default: head)
        downgrade <revision> - Rollback to a specific revision
        current              - Show current migration revision
        history              - Show migration history
        revision <message>   - Create a new migration (with --autogenerate)
        heads                - Show current head revision(s)
        merge                - Create a merge migration (default: merge all heads)
        show <revision>      - Show a specific migration's details
        stamp <revision>     - Set DB revision without running migrations

    Examples:
        # Create a migration from model changes
        uv run api-forge-cli dev db migrate revision -m "add widget"

        # Apply all pending migrations
        uv run api-forge-cli dev db migrate upgrade

        # Roll back one migration
        uv run api-forge-cli dev db migrate downgrade -1

        # Inspect migration state
        uv run api-forge-cli dev db migrate current
        uv run api-forge-cli dev db migrate history
    """
    success = run_migration(
        action=action,
        revision=revision,
        message=message,
        merge_revisions=merge_revisions or [],
        purge=purge,
        autogenerate=autogenerate,
        sql=sql,
        database_url=get_dev_database_url(),
        console=console,
    )

    if not success:
        raise typer.Exit(1)
