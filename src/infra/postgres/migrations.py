from __future__ import annotations

import os
import subprocess

from src.utils.console_like import ConsoleLike
from src.utils.paths import get_project_root


def run_migration(
    *,
    action: str,
    revision: str | None,
    message: str | None,
    merge_revisions: list[str],
    purge: bool,
    autogenerate: bool,
    sql: bool,
    database_url: str,
    console: ConsoleLike,
) -> bool:
    """Run Alembic migration command.

    This function is called inside a port-forward context (if bundled postgres).
    """
    project_root = get_project_root()
    alembic_ini = project_root / "alembic.ini"

    if not alembic_ini.exists():
        console.error(f"Alembic configuration not found: {alembic_ini}")
        console.print("\n[dim]Initialize Alembic with:[/dim]")
        console.print("  alembic init migrations")
        return False

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url

    # Build alembic command
    alembic_args = ["alembic", "-c", str(alembic_ini)]

    if sql and action not in {"upgrade", "downgrade"}:
        console.error("--sql is only supported for upgrade/downgrade")
        return False

    if action == "upgrade":
        target = revision or "head"
        alembic_args.extend(["upgrade", target])
        if sql:
            alembic_args.append("--sql")
        console.info(f"Applying migrations to: {target}")

    elif action == "downgrade":
        if not revision:
            console.error("Downgrade requires a target revision")
            console.print("\n[dim]Examples:[/dim]")
            console.print("  ... db migrate downgrade abc123")
            console.print("  ... db migrate downgrade -1")
            return False
        alembic_args.extend(["downgrade", revision])
        if sql:
            alembic_args.append("--sql")
        console.warn(f"Rolling back to: {revision}")

    elif action == "current":
        alembic_args.append("current")
        console.info("Showing current migration state...")

    elif action == "history":
        alembic_args.extend(["history", "--verbose"])
        console.info("Showing migration history...")

    elif action == "heads":
        alembic_args.extend(["heads", "--verbose"])
        console.info("Showing current migration heads...")

    elif action == "show":
        if not revision:
            console.error("Show requires a revision")
            console.print("\n[dim]Example:[/dim]")
            console.print("  ... db migrate show 19becf30b774")
            return False
        alembic_args.extend(["show", revision])
        console.info(f"Showing migration: {revision}")

    elif action == "stamp":
        if not revision:
            console.error("Stamp requires a target revision")
            console.print("\n[dim]Examples:[/dim]")
            console.print("  ... db migrate stamp head")
            console.print("  ... db migrate stamp 19becf30b774")
            return False
        alembic_args.extend(["stamp", revision])
        if purge:
            alembic_args.append("--purge")
        console.warn(
            "Stamping the database (no migrations executed). "
            "Use only when you understand the implications."
        )

    elif action == "merge":
        merge_message = message or revision or "merge heads"
        revisions_to_merge = merge_revisions or ["heads"]
        alembic_args.extend(["merge", "-m", merge_message, *revisions_to_merge])
        console.info(
            f"Creating merge migration: {merge_message} "
            f"(revisions: {', '.join(revisions_to_merge)})"
        )

    elif action == "revision":
        if not revision:
            console.error("Revision requires a message")
            console.print("\n[dim]Example:[/dim]")
            console.print('  ... db migrate revision "add user table"')
            return False
        alembic_args.extend(["revision", "-m", revision])
        if autogenerate:
            alembic_args.append("--autogenerate")
            console.info(f"Generating migration: {revision} (with autogeneration)")
        else:
            console.info(f"Creating empty migration: {revision}")

    else:
        console.error(f"Unknown action: {action}")
        console.print(
            "\n[dim]Valid actions: upgrade, downgrade, current, history, revision, "
            "heads, merge, show, stamp[/dim]"
        )
        return False

    # Run alembic command
    result = subprocess.run(
        alembic_args,
        capture_output=True,
        text=True,
        cwd=str(project_root),
        env=env,
    )

    if result.returncode != 0:
        console.error(f"Migration failed:\n{result.stderr}")
        if result.stdout:
            console.print(result.stdout)
        return False

    # Show output (stdout and stderr, as Alembic uses both)
    if result.stdout.strip():
        console.print(result.stdout)
    if result.stderr.strip():
        console.print(result.stderr)

    # If no output, provide helpful message based on action
    if not result.stdout.strip() and not result.stderr.strip():
        if action == "current":
            console.print("[dim]No migrations applied yet.[/dim]")
        elif action == "history":
            console.print("[dim]No migration history found.[/dim]")

    if action == "upgrade":
        console.ok("Migrations applied successfully")
    elif action == "downgrade":
        console.ok("Rollback completed successfully")
    elif action == "revision":
        console.ok("Migration file created successfully")
        console.print("\n[dim]Next steps:[/dim]")
        console.print("  1. Review the generated migration in migrations/versions/")
        console.print("  2. Run '... db migrate upgrade' to apply it")
    elif action == "merge":
        console.ok("Merge migration created successfully")

    return True
