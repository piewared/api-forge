"""Shared database workflows for CLI commands."""

from __future__ import annotations

from pathlib import Path

import typer

from src.cli.commands.db.runtime import DbRuntime
from src.infra.postgres.migrations import run_migration


def run_init(runtime: DbRuntime) -> bool:
    from src.infra.postgres import PostgresInitializer

    settings = runtime.get_settings().ensure_all_passwords()
    with runtime.port_forward():
        with runtime.connect(settings, True) as conn:
            initializer = PostgresInitializer(connection=conn)
            return initializer.initialize()


def run_verify(runtime: DbRuntime, *, superuser_mode: bool) -> bool:
    from src.infra.postgres import PostgresVerifier

    settings = runtime.get_settings().ensure_all_passwords()
    with runtime.port_forward():
        with runtime.connect(settings, superuser_mode) as conn:
            verifier = PostgresVerifier(connection=conn)
            return verifier.verify_all()


def run_sync(runtime: DbRuntime) -> bool:
    from src.infra.postgres import PostgresPasswordSync

    settings = runtime.get_settings()
    success = True

    if runtime.is_bundled_postgres_enabled():
        runtime.console.print_subheader("Syncing bundled PostgreSQL superuser password")
        with runtime.port_forward():
            with runtime.connect(settings, True) as conn:
                sync_tool = PostgresPasswordSync(
                    connection=conn,
                    deployer=runtime.get_deployer(),
                    secrets_dirs=list(runtime.secrets_dirs),
                )
                success = sync_tool.sync_bundled_superuser_password()

    with runtime.port_forward():
        with runtime.connect(settings, True) as conn:
            sync_tool = PostgresPasswordSync(
                connection=conn,
                deployer=runtime.get_deployer(),
                secrets_dirs=list(runtime.secrets_dirs),
            )
            runtime.console.print_subheader(
                "Syncing application database user roles and passwords"
            )
            user_success = sync_tool.sync_user_roles_and_passwords()
            success = success and user_success

    return success


def run_backup(
    runtime: DbRuntime, *, output_dir: Path, superuser_mode: bool
) -> tuple[bool, str]:
    from src.infra.postgres import PostgresBackup

    settings = runtime.get_settings()
    with runtime.port_forward():
        with runtime.connect(settings, superuser_mode) as conn:
            backup_tool = PostgresBackup(
                connection=conn,
                backup_dir=output_dir,
            )
            return backup_tool.create_backup()


def run_reset(
    runtime: DbRuntime, *, include_temporal: bool, superuser_mode: bool
) -> bool:
    from src.infra.postgres import PostgresReset

    settings = runtime.get_settings()
    with runtime.port_forward():
        with runtime.connect(settings, superuser_mode) as conn:
            reset_tool = PostgresReset(connection=conn)
            return reset_tool.reset(include_temporal=include_temporal)


def run_status(runtime: DbRuntime, *, superuser_mode: bool) -> None:
    import time

    from rich.table import Table

    settings = runtime.get_settings()

    try:
        start = time.perf_counter()
        with runtime.port_forward():
            with runtime.connect(settings, superuser_mode) as conn:
                latency_ms = (time.perf_counter() - start) * 1000

                perf_table = Table(title="Connection & Performance")
                perf_table.add_column("Metric", style="cyan")
                perf_table.add_column("Value", style="green")

                perf_table.add_row("Host", f"{settings.host}:{settings.port}")
                perf_table.add_row("Connection Latency", f"{latency_ms:.2f} ms")

                try:
                    uptime = conn.scalar(
                        "SELECT EXTRACT(EPOCH FROM (now() - pg_postmaster_start_time()));"
                    )
                    if uptime:
                        hours = int(uptime // 3600)
                        minutes = int((uptime % 3600) // 60)
                        perf_table.add_row("Uptime", f"{hours}h {minutes}m")
                except Exception:
                    pass

                try:
                    active_conns = conn.scalar(
                        "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"
                    )
                    total_conns = conn.scalar("SELECT count(*) FROM pg_stat_activity;")
                    max_conns = conn.scalar(
                        "SELECT setting::int FROM pg_settings WHERE name = 'max_connections';"
                    )
                    perf_table.add_row(
                        "Connections",
                        f"{active_conns} active / {total_conns} total / {max_conns} max",
                    )
                except Exception:
                    pass

                try:
                    cache_hit = conn.scalar(
                        """
                        SELECT ROUND(
                            100.0 * sum(blks_hit) / NULLIF(sum(blks_hit) + sum(blks_read), 0),
                            2
                        )
                        FROM pg_stat_database;
                        """
                    )
                    if cache_hit is not None:
                        color = (
                            "green"
                            if cache_hit >= 90
                            else "yellow"
                            if cache_hit >= 75
                            else "red"
                        )
                        perf_table.add_row(
                            "Cache Hit Ratio", f"[{color}]{cache_hit}%[/{color}]"
                        )
                except Exception:
                    pass

                runtime.console.print(perf_table)

                size_table = Table(title="\nDatabase Sizes")
                size_table.add_column("Database", style="cyan")
                size_table.add_column("Size", style="green")
                size_table.add_column("Tables", style="blue")

                databases_to_check = [settings.app_db]
                if runtime.is_temporal_enabled():
                    databases_to_check.extend(["temporal", "temporal_visibility"])

                for db_name in databases_to_check:
                    try:
                        db_size = conn.scalar(
                            "SELECT pg_size_pretty(pg_database_size(%s));",
                            (db_name,),
                        )
                        table_count = conn.scalar(
                            """
                            SELECT count(*)
                            FROM pg_catalog.pg_tables
                            WHERE schemaname NOT IN ('pg_catalog', 'information_schema');
                            """,
                            database=db_name,
                        )
                        row_count_query = """
                            SELECT SUM(n_live_tup)
                            FROM pg_stat_user_tables;
                        """
                        row_count = conn.scalar(row_count_query, database=db_name) or 0

                        if table_count and table_count > 0:
                            size_table.add_row(
                                db_name,
                                db_size or "unknown",
                                f"{table_count} tables, ~{row_count:,} rows",
                            )
                        else:
                            size_table.add_row(
                                db_name,
                                db_size or "unknown",
                                "[dim]no tables[/dim]",
                            )
                    except Exception:
                        pass

                runtime.console.print(size_table)

    except Exception as exc:
        runtime.console.error(f"Failed to connect: {exc}")
        runtime.console.print(
            "\n[dim]Check your database configuration and connectivity[/dim]"
        )
        runtime.console.print(f"[dim]Host: {settings.host}:{settings.port}[/dim]")


def run_migrate(
    runtime: DbRuntime,
    *,
    action: str,
    revision: str | None,
    message: str | None,
    merge_revisions: list[str],
    purge: bool,
    autogenerate: bool,
    sql: bool,
) -> None:
    settings = runtime.get_settings().ensure_superuser_password()

    with runtime.port_forward():
        conn = runtime.connect(settings, True)
        database_url = conn.get_connection_string()

        success = run_migration(
            action=action,
            revision=revision,
            message=message,
            merge_revisions=merge_revisions,
            purge=purge,
            autogenerate=autogenerate,
            sql=sql,
            database_url=database_url,
            console=runtime.console,
        )

    if not success:
        raise typer.Exit(1)
