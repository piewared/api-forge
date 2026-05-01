"""Fly.io ``sync`` command — push current code to the main app.

This is the tight code-iteration cousin of ``fly up``:

- ``fly up``  reconciles the whole stack (supporting services + main app).
  Use it on first deploy, after infra changes, or after a config flip.
- ``fly sync`` builds and ships the main app image and nothing else.
  Use it dozens of times a day during development.

The deploy pipeline itself (ensure-app + secrets + db check + fly.toml +
``fly deploy``) is shared with ``up`` via ``_main_app_deploy.deploy_main_app``
so the two commands cannot drift apart.
"""

from __future__ import annotations

from typing import Annotated

import typer

from src.cli.commands.fly._prereq import check_prerequisites, get_fly_controller
from src.cli.shared.console import console, with_error_handling

from . import fly_app
from ._main_app_deploy import deploy_main_app
from .deploy import _check_database_exists
from .service_deploy import _check_app_machine_status
from .settings import _get_app_name, _load_fly_app_settings


@fly_app.command()
@with_error_handling
def sync(
    app: Annotated[
        str | None,
        typer.Option(
            "--app",
            "-a",
            help="App name (from config if not specified)",
        ),
    ] = None,
    region: Annotated[
        str | None,
        typer.Option(
            "--region",
            "-r",
            help="Primary region (from config if not specified)",
        ),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option(
            "--org",
            "-o",
            help="Fly.io organization (from config if not specified)",
        ),
    ] = None,
    dockerfile: Annotated[
        str,
        typer.Option(
            "--dockerfile",
            help="Path to Dockerfile",
        ),
    ] = "Dockerfile",
    image: Annotated[
        str | None,
        typer.Option(
            "--image",
            "-i",
            help="Pre-built image to deploy (skips build)",
        ),
    ] = None,
    strategy: Annotated[
        str | None,
        typer.Option(
            "--strategy",
            "-s",
            help="Deployment strategy (canary, bluegreen, rolling, immediate)",
        ),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache",
            help="Build without cache",
        ),
    ] = False,
    regenerate_config: Annotated[
        bool,
        typer.Option(
            "--regenerate-config",
            help="Regenerate fly.toml even if it exists",
        ),
    ] = False,
    skip_db_check: Annotated[
        bool,
        typer.Option(
            "--skip-db-check",
            help="Skip database verification before deployment",
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Show bookkeeping output (per-secret confirmations, file generation, etc.).",
        ),
    ] = False,
) -> None:
    """Push current code to the main app on Fly.io.

    Faster, narrower cousin of ``fly up``: skips the supporting-services phase
    (Redis / Temporal) and the multi-app pre-flight survey. Pre-flight is just
    a single main-app machine probe and (optionally) a database existence
    check.

    Examples:

        # Build local code and ship to the configured Fly app
        api-forge-cli fly sync

        # Ship a pre-built image (no Dockerfile build)
        api-forge-cli fly sync --image registry.fly.io/my-app:v2

        # Force a full rebuild (no Docker layer cache)
        api-forge-cli fly sync --no-cache

        # Skip the database attachment check (e.g., external Postgres)
        api-forge-cli fly sync --skip-db-check
    """
    console.set_verbose(verbose)
    controller = get_fly_controller()
    check_prerequisites(controller)

    settings = _load_fly_app_settings()
    effective_app = _get_app_name(app, settings)
    effective_region = region or settings.region
    effective_org = org or settings.org

    console.print_header("Sync to Fly.io")
    console.print(f"  [bold]App[/bold]    {effective_app}")
    console.print(f"  [bold]Region[/bold] {effective_region}")

    # ---- Minimal pre-flight ----
    # Only what's needed to fail fast on a misconfigured environment:
    # database existence (if checked) and the main app's machine state.
    cluster_name: str | None = None
    if not skip_db_check:
        db_exists, cluster_name = _check_database_exists(controller)
        if not db_exists:
            console.error("Database not found")
            if cluster_name:
                console.print(f"  Configured cluster '{cluster_name}' does not exist.")
            else:
                console.print("  No database cluster configured in config.yaml.")
            console.print()
            console.print("  Create one:  uv run api-forge-cli fly db create managed")
            console.print("  Or skip:     api-forge-cli fly sync --skip-db-check")
            raise typer.Exit(1)

    # Quick main-app machine probe (will be woken automatically before deploy).
    _check_app_machine_status(controller, effective_app, label="app")

    # ---- Deploy ----
    console.print_subheader("Main App")
    result = deploy_main_app(
        controller,
        effective_app=effective_app,
        effective_region=effective_region,
        effective_org=effective_org,
        cluster_name=cluster_name,
        dockerfile=dockerfile,
        image=image,
        strategy=strategy,
        no_cache=no_cache,
        regenerate_config=regenerate_config,
        skip_db_check=skip_db_check,
    )

    # ---- Result ----
    console.print()
    if result.success:
        console.ok(f"Synced — https://{effective_app}.fly.dev")
    else:
        console.error("Sync failed")
        if result.stderr:
            console.print(f"[dim]{result.stderr}[/dim]")
        raise typer.Exit(1)
