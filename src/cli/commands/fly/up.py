"""Fly.io 'up' command — full deployment workflow."""

import concurrent.futures
import time
from typing import Annotated

import typer
from rich.table import Table

from src.cli.shared.console import console, with_error_handling
from src.cli.shared.fly import check_prerequisites, get_fly_controller
from src.infra.flyio.controller import FlyCtlControllerSync
from src.infra.flyio.temporal import (
    run_temporal_namespace_init,
    run_temporal_schema_setup,
)

# fly_app is imported here so the decorator registers the command on it
from . import fly_app
from ._main_app_deploy import deploy_main_app
from .deploy import _check_database_exists
from .service_deploy import (
    SERVICE_SPECS,
    _check_app_machine_status,
    _deploy_service_app,
    _generate_service_app_name,
)
from .settings import (
    _check_service_enabled,
    _get_app_name,
    _load_env_file,
    _load_fly_app_settings,
)

# Time to wait after the Temporal server's machine reports healthy before
# running namespace-init / starting the worker. ``fly deploy`` returns when
# the health check passes, but the gRPC server (port 7233) may still be
# initialising its DB connections. 20s gives consistent results in practice.
_TEMPORAL_GRPC_WARMUP_SECONDS = 20

# Valid choices for ``--service``. Derived from ``SERVICE_SPECS`` (the source
# of truth for supporting services) plus ``"app"`` for the main application.
_VALID_ONLY_SERVICES = frozenset(SERVICE_SPECS.keys()) | {"app"}


def _temporal_namespace_init_fallback_command(temporal_app_name: str) -> str:
    """Manual ``fly machines run`` invocation users can copy-paste if the
    automated namespace-init step fails. Centralised so the version pin and
    flags stay consistent across the multiple call sites that surface it."""
    return (
        "    fly machines run "
        "temporalio/admin-tools:1.29.0-tctl-1.18.4-cli-1.4.2 "
        f"--app {temporal_app_name} "
        f"-- temporal --address {temporal_app_name}.internal:7233 "
        "operator namespace create -n default --retention 7d"
    )


def _deploy_redis_service(
    controller: FlyCtlControllerSync,
    effective_app: str,
    effective_region: str,
    effective_org: str | None,
) -> tuple[bool, tuple[str, str, int] | None]:
    """Deploy Redis as a separate Fly app. Returns (success, service_entry_or_None)."""
    redis_app_name = _generate_service_app_name(effective_app, "redis")
    ok = _deploy_service_app(
        controller,
        "Redis",
        redis_app_name,
        "redis",
        effective_region,
        effective_org,
        internal_port=6379,
        memory="512mb",
    )
    return ok, ("Redis", redis_app_name, 6379) if ok else None


def _run_temporal_schema(
    controller: FlyCtlControllerSync,
    effective_app: str,
    cluster_name: str | None,
    effective_region: str,
) -> bool:
    """Run Temporal schema setup one-shot machine. Returns success flag."""
    temporal_app_name = _generate_service_app_name(effective_app, "temporal")
    console.step("Running Temporal schema setup (one-shot machine)...")
    ok = run_temporal_schema_setup(
        controller,
        temporal_app_name=temporal_app_name,
        cluster_name=cluster_name,
        env_lookup=_load_env_file(include_fly_overrides=True),
        region=effective_region,
        console=console,
    )
    if not ok:
        console.warn(
            "Schema setup failed or was skipped — "
            "Temporal server may not start correctly."
        )
    return ok


def _run_namespace_init(
    controller: FlyCtlControllerSync,
    temporal_app_name: str,
    effective_region: str,
) -> bool:
    """Run Temporal namespace init one-shot machine. Returns success flag."""
    console.step("Running Temporal namespace init (one-shot machine)...")
    ok = run_temporal_namespace_init(
        controller,
        temporal_app_name=temporal_app_name,
        region=effective_region,
        console=console,
    )
    if not ok:
        console.warn(
            "Namespace init failed — create it manually:\n"
            + _temporal_namespace_init_fallback_command(temporal_app_name)
        )
    return ok


def _deploy_temporal_web_service(
    controller: FlyCtlControllerSync,
    effective_app: str,
    effective_region: str,
    effective_org: str | None,
) -> tuple[bool, tuple[str, str, int] | None]:
    """Deploy Temporal Web UI as a separate Fly app. Returns (success, service_entry_or_None)."""
    temporal_web_app_name = _generate_service_app_name(effective_app, "temporal-web")
    ok = _deploy_service_app(
        controller,
        "Temporal Web",
        temporal_web_app_name,
        "temporal-web",
        effective_region,
        effective_org,
        internal_port=8080,
        memory="256mb",
    )
    return ok, ("Temporal Web", temporal_web_app_name, 8080) if ok else None


@fly_app.command()
@with_error_handling
def up(
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
    only_service: Annotated[
        str | None,
        typer.Option(
            "--service",
            "-S",
            help=(
                "Deploy only this one service and exit. "
                "Choices: redis, temporal, temporal-web, worker, app. "
                "Skips all other phases — useful for targeted redeployment "
                "and iterating on a single service without running the full pipeline."
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Show bookkeeping output (per-secret confirmations, file generation, etc.).",
        ),
    ] = False,
) -> None:
    """Deploy to Fly.io (analogous to k8s up).

    This command handles the complete deployment workflow, deploying all
    enabled services as separate Fly apps (mirrors k8s Helm deployment):

    Phase 0: Pre-flight checks (database, enabled services)
    Phase 1: Deploy supporting services as separate Fly apps:
        - Redis (if redis.enabled: true)
        - Temporal server (if temporal.enabled: true)
        - Temporal Web UI (if temporal.enabled: true)
        - Worker (if temporal.enabled: true)
    Phase 2: Main app setup + sync secrets (so DATABASE_URL is present for attachment check)
    Phase 3: Configuration (generate fly.toml)
    Phase 4: Deploy main application
    Phase 5: Post-deployment summary

    Services are deployed using Docker images from infra/docker/prod/:
    - Redis: infra/docker/prod/redis/Dockerfile
    - Temporal: infra/docker/prod/temporal/Dockerfile
    - Temporal Web: temporalio/ui:2.34.0 (official image)
    - Worker: Dockerfile (same as main app, runs in worker mode)
    - App: Dockerfile in project root

    Each service is deployed as a separate Fly app:
    - Main app: {app-name}
    - Redis: {app-name}-redis
    - Temporal: {app-name}-temporal
    - Temporal Web: {app-name}-temporal-web
    - Worker: {app-name}-worker

    Services communicate via Fly's private network using .flycast addresses.

    Examples:
        # Deploy using config defaults (deploys all enabled services)
        uv run api-forge-cli fly up

        # Deploy with custom app name
        uv run api-forge-cli fly up --app my-app

        # Deploy to specific region
        uv run api-forge-cli fly up --region lhr

        # Deploy pre-built image
        uv run api-forge-cli fly up --image registry.fly.io/my-app:v1.0

        # Force regenerate fly.toml
        uv run api-forge-cli fly up --regenerate-config

        # Skip database check (if using external database)
        uv run api-forge-cli fly up --skip-db-check

        # Deploy only the Temporal service (schema setup + server)
        uv run api-forge-cli fly up --service temporal

        # Deploy only Redis
        uv run api-forge-cli fly up --service redis

        # Re-deploy main app only
        uv run api-forge-cli fly up --service app
    """
    console.set_verbose(verbose)
    controller = get_fly_controller()
    check_prerequisites(controller)

    # Load settings from config
    settings = _load_fly_app_settings()

    # Determine effective values
    effective_app = _get_app_name(app, settings)
    effective_region = region or settings.region
    effective_org = org or settings.org

    console.print_header("Deploy to Fly.io")
    # Run metadata as a clean key:value block (no bullet chrome).
    console.print(f"  [bold]App[/bold]          {effective_app}")
    console.print(f"  [bold]Region[/bold]       {effective_region}")
    if effective_org:
        console.print(f"  [bold]Organization[/bold] {effective_org}")

    # Validate --service value early so the error is immediate.
    if only_service and only_service not in _VALID_ONLY_SERVICES:
        console.error(
            f"Unknown service '{only_service}'. "
            f"Valid choices: {', '.join(sorted(_VALID_ONLY_SERVICES))}"
        )
        raise typer.Exit(1)

    # =========================================================================
    # Phase 0: Pre-flight checks (analogous to k8s up validation)
    # =========================================================================
    console.print_subheader("Phase 0: Pre-flight Checks")

    # Check enabled services in config.yaml (skip noise when targeting one service)
    if not only_service:
        redis_enabled = _check_service_enabled("redis")
        temporal_enabled = _check_service_enabled("temporal")
        console.debug(f"redis enabled in config: {redis_enabled}")
        console.debug(f"temporal enabled in config: {temporal_enabled}")
    else:
        redis_enabled = False
        temporal_enabled = False

    # cluster_name is resolved by the DB check below; initialised here so it
    # is always defined regardless of skip_db_check / only_service.
    cluster_name: str | None = None

    # Check database setup (unless skipped)
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
            console.print("  Or skip:     api-forge-cli fly up --skip-db-check")
            raise typer.Exit(1)

        console.ok(f"Database cluster found: {cluster_name}")

    # Check machine status of target app(s) and warn if any are not running.
    console.step("Checking machine status...")
    if only_service and only_service in {"redis", "temporal", "temporal-web", "worker"}:
        # Targeting a single supporting service — check only that app.
        _check_app_machine_status(
            controller,
            _generate_service_app_name(effective_app, only_service),
            label=only_service,
        )
    elif only_service == "app" or only_service is None:
        # Full deploy or main-app-only — check the main app.
        _check_app_machine_status(controller, effective_app, label="app")
        if only_service is None:
            # Also check each enabled supporting service.
            if _check_service_enabled("redis"):
                _check_app_machine_status(
                    controller,
                    _generate_service_app_name(effective_app, "redis"),
                    label="redis",
                )
            if _check_service_enabled("temporal"):
                for svc in ("temporal", "temporal-web", "worker"):
                    _check_app_machine_status(
                        controller,
                        _generate_service_app_name(effective_app, svc),
                        label=svc,
                    )

    console.print()

    # =========================================================================
    # Single-service fast path
    # =========================================================================
    if only_service and only_service in SERVICE_SPECS:
        display_name, compose_name, port, memory = SERVICE_SPECS[only_service]
        console.print_subheader(f"Deploying service: {display_name}")

        if only_service == "temporal":
            # Schema setup must run before the Temporal server starts.
            console.step("Running Temporal schema setup (one-shot machine)...")
            schema_ok = run_temporal_schema_setup(
                controller,
                temporal_app_name=_generate_service_app_name(effective_app, "temporal"),
                cluster_name=cluster_name,
                env_lookup=_load_env_file(include_fly_overrides=True),
                region=effective_region,
                console=console,
            )
            if not schema_ok:
                console.warn(
                    "Schema setup failed — server deploy will continue but "
                    "Temporal may not start correctly."
                )
            console.print()

        ok = _deploy_service_app(
            controller,
            display_name,
            _generate_service_app_name(effective_app, only_service),
            compose_name,
            effective_region,
            effective_org,
            internal_port=port,
            memory=memory,
            base_app_name=effective_app,
        )

        if only_service == "temporal" and ok:
            temporal_app_name = _generate_service_app_name(effective_app, "temporal")
            console.step(
                f"Waiting {_TEMPORAL_GRPC_WARMUP_SECONDS}s for Temporal "
                "gRPC server to initialise..."
            )
            time.sleep(_TEMPORAL_GRPC_WARMUP_SECONDS)
            console.step("Running Temporal namespace init (one-shot machine)...")
            ns_ok = run_temporal_namespace_init(
                controller,
                temporal_app_name=temporal_app_name,
                region=effective_region,
                console=console,
            )
            if not ns_ok:
                console.warn(
                    "Namespace init failed — create it manually:\n"
                    + _temporal_namespace_init_fallback_command(temporal_app_name)
                )

        raise typer.Exit(0 if ok else 1)

    # =========================================================================
    # Phase 1: Deploy Supporting Services (Redis, Temporal)
    # =========================================================================
    services_deployed = []
    services_failed = []
    # Tri-state: None = not attempted (Temporal disabled), True/False = result
    # of the explicit one-shot schema setup. Surfaced in the summary table so a
    # silent failure on a pre-initialised DB is still visible to operators.
    temporal_schema_status: bool | None = None

    # only_service == "app" skips Phase 1 entirely; None runs all enabled services.
    if (only_service is None) and (redis_enabled or temporal_enabled):
        console.print_subheader("Phase 1: Deploy Supporting Services")

        # --- Group A (parallel): Redis + Temporal schema setup ---
        # Neither depends on the other, so both can start immediately.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            redis_future = (
                pool.submit(
                    _deploy_redis_service,
                    controller,
                    effective_app,
                    effective_region,
                    effective_org,
                )
                if redis_enabled
                else None
            )
            schema_future = (
                pool.submit(
                    _run_temporal_schema,
                    controller,
                    effective_app,
                    cluster_name,
                    effective_region,
                )
                if temporal_enabled
                else None
            )

            if redis_future is not None:
                redis_ok, redis_entry = redis_future.result()
                if redis_ok and redis_entry:
                    services_deployed.append(redis_entry)
                elif not redis_ok:
                    services_failed.append("Redis")

            # Temporal server deploy continues regardless — a failure here is
            # benign if the DB schema is already current. The status flows into
            # the summary table so an unexpected failure on a fresh DB stays
            # visible.
            if schema_future is not None:
                temporal_schema_status = schema_future.result()

        # --- Sequential: Temporal server (requires schema to exist) ---
        if temporal_enabled:
            temporal_app_name = _generate_service_app_name(effective_app, "temporal")
            temporal_server_ok = _deploy_service_app(
                controller,
                "Temporal",
                temporal_app_name,
                "temporal",
                effective_region,
                effective_org,
                internal_port=7233,
                memory="1gb",
            )

            if temporal_server_ok:
                services_deployed.append(("Temporal", temporal_app_name, 7233))

                # Give Temporal's gRPC server a short head-start. fly deploy
                # returns once the health check passes, but port 7233 may
                # still be initialising its DB connections.
                console.step(
                    f"Waiting {_TEMPORAL_GRPC_WARMUP_SECONDS}s for Temporal "
                    "gRPC server to initialise..."
                )
                time.sleep(_TEMPORAL_GRPC_WARMUP_SECONDS)

                # --- Sequential: namespace-init (must complete before worker starts) ---
                # Running this in parallel with Temporal Web deploy caused flyctl
                # spinner frames from the Web deploy to interleave with health-check
                # output from the machine, making logs unreadable.
                _ns_ok = _run_namespace_init(
                    controller,
                    temporal_app_name,
                    effective_region,
                )

                # --- Sequential: Temporal Web UI (after namespace init, no dependency) ---
                web_ok, web_entry = _deploy_temporal_web_service(
                    controller,
                    effective_app,
                    effective_region,
                    effective_org,
                )
                if web_ok and web_entry:
                    services_deployed.append(web_entry)
                elif not web_ok:
                    services_failed.append("Temporal Web")

                # --- Sequential: Worker (needs namespace + Redis both done) ---
                worker_app_name = _generate_service_app_name(effective_app, "worker")
                if _deploy_service_app(
                    controller,
                    "Worker",
                    worker_app_name,
                    "worker",
                    effective_region,
                    effective_org,
                    internal_port=8000,
                    memory="512mb",
                    base_app_name=effective_app,
                ):
                    services_deployed.append(("Worker", worker_app_name, 8000))
                else:
                    services_failed.append("Worker")
            else:
                services_failed.append("Temporal")

        if services_failed:
            console.error(f"Failed to deploy services: {', '.join(services_failed)}")
            console.info("Continuing with main app deployment...")

    # =========================================================================
    # Main App: setup, configuration, deploy
    # =========================================================================
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

    if result.success:
        console.ok("Deployment completed")

        # =====================================================================
        # Summary
        # =====================================================================
        console.print_subheader("Summary")

        # ----- Top: app URL (and Temporal Web UI if present) -----
        temporal_deployed = any(s[0] == "Temporal" for s in services_deployed)
        temporal_web_deployed = any(s[0] == "Temporal Web" for s in services_deployed)
        console.print(f"  [bold]App:[/bold]         https://{effective_app}.fly.dev")
        if temporal_web_deployed:
            web_app = _generate_service_app_name(effective_app, "temporal-web")
            console.print(f"  [bold]Temporal UI:[/bold] https://{web_app}.fly.dev")
        console.print()

        # ----- Service status table (single source of truth for addresses) -----
        table = Table(show_header=True, header_style="bold")
        table.add_column("Service")
        table.add_column("Status")
        table.add_column("Address")

        table.add_row(
            "App",
            "[green]✓ Deployed[/green]",
            f"{effective_app}.fly.dev",
        )

        if not skip_db_check and cluster_name:
            table.add_row(
                "PostgreSQL",
                "[green]✓ Connected[/green]",
                f"cluster: {cluster_name}",
            )

        for service_name, service_app, port in services_deployed:
            table.add_row(
                service_name,
                "[green]✓ Deployed[/green]",
                f"{service_app}.flycast:{port}",
            )

        for service_name in services_failed:
            table.add_row(
                service_name,
                "[red]✗ Failed[/red]",
                "(see logs above)",
            )

        # Surface the explicit Temporal schema-setup result. Failure is non-fatal
        # because update-schema is a no-op against an already-current DB; it's
        # only a real problem on a truly fresh database.
        if temporal_schema_status is True:
            table.add_row(
                "Temporal Schema",
                "[green]✓ Up to date[/green]",
                "schema + visibility tables current",
            )
        elif temporal_schema_status is False:
            table.add_row(
                "Temporal Schema",
                "[yellow]⚠ Setup failed[/yellow]",
                "benign if DB pre-initialised; fatal on fresh DB",
            )

        console.print(table)
        console.print()

        # ----- Schema-setup failure: detailed recovery hints -----
        if temporal_schema_status is False and temporal_deployed:
            temporal_app_name = _generate_service_app_name(effective_app, "temporal")
            console.warn(
                "Temporal schema setup failed this run. update-schema is "
                "idempotent — if your DB was initialised by a previous deploy, "
                "this is benign. On a fresh DB, Temporal will not start."
            )
            console.print(f"  [dim]Inspect:[/dim] fly logs --app {temporal_app_name}")
            console.print("  [dim]Rerun:[/dim]   uv run api-forge-cli fly up")
            console.print()

        # ----- Useful commands (compact two-column layout) -----
        console.print("[bold]Useful commands[/bold]")
        console.print(
            "  uv run api-forge-cli fly status   [dim]· health & machines[/dim]"
        )
        console.print("  uv run api-forge-cli fly logs     [dim]· tail app logs[/dim]")
        console.print(
            "  uv run api-forge-cli fly scale --count 2   [dim]· scale machines[/dim]"
        )
    else:
        console.error("Deployment failed")
        if result.stderr:
            console.print(f"[dim]{result.stderr}[/dim]")
        raise typer.Exit(1)
