"""Fly.io 'up' command — full deployment workflow."""

import concurrent.futures
import time
from typing import Annotated

import typer
from rich.table import Table

from src.cli.shared.console import console, with_error_handling
from src.cli.shared.fly import check_prerequisites, get_fly_controller
from src.infra.flyio.controller import FlyCtlControllerSync
from src.infra.flyio.port_forward import ensure_app_machines_running
from src.infra.flyio.temporal import (
    run_temporal_namespace_init,
    run_temporal_schema_setup,
)
from src.utils.paths import get_project_root

# fly_app is imported here so the decorator registers the command on it
from . import fly_app
from .deploy import _check_database_attached, _check_database_exists, _ensure_app_exists
from .secrets import _sync_secrets
from .service_deploy import (
    SERVICE_SPECS,
    _check_app_machine_status,
    _deploy_service_app,
    _generate_service_app_name,
    _inject_fly_service_urls,
)
from .settings import (
    _check_service_enabled,
    _get_app_name,
    _load_env_file,
    _load_fly_app_settings,
)
from .toml import _fly_toml_exists, _get_fly_toml_path, _write_fly_toml

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
    console.info("Running Temporal schema setup (one-shot machine)...")
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
            "  Schema setup failed or was skipped — "
            "Temporal server may not start correctly."
        )
    return ok


def _run_namespace_init(
    controller: FlyCtlControllerSync,
    temporal_app_name: str,
    effective_region: str,
) -> bool:
    """Run Temporal namespace init one-shot machine. Returns success flag."""
    console.info("Running Temporal namespace init (one-shot machine)...")
    ok = run_temporal_namespace_init(
        controller,
        temporal_app_name=temporal_app_name,
        region=effective_region,
        console=console,
    )
    if not ok:
        console.warn(
            "  Namespace init failed — create it manually:\n"
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
    controller = get_fly_controller()
    check_prerequisites(controller)

    # Load settings from config
    settings = _load_fly_app_settings()

    # Determine effective values
    effective_app = _get_app_name(app, settings)
    effective_region = region or settings.region
    effective_org = org or settings.org

    console.print_header("Deploy to Fly.io")
    console.info(f"App: {effective_app}")
    console.info(f"Region: {effective_region}")
    if effective_org:
        console.info(f"Organization: {effective_org}")
    console.print()

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
        console.info(f"Redis enabled in config: {redis_enabled}")
        console.info(f"Temporal enabled in config: {temporal_enabled}")
        console.print()
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
            console.error("Database not found!")
            if cluster_name:
                console.info(f"  Configured cluster '{cluster_name}' does not exist.")
            else:
                console.info("  No database cluster configured in config.yaml.")
            console.print()
            console.info("Create a database first:")
            console.info("  uv run api-forge-cli fly db create managed")
            console.print()
            console.info("Or skip this check with --skip-db-check")
            raise typer.Exit(1)

        console.ok(f"Database cluster found: {cluster_name}")

    # Check machine status of target app(s) and warn if any are not running.
    console.info("Checking machine status...")
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
            console.info("Running Temporal schema setup (one-shot machine)...")
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
            console.info(
                f"  Waiting {_TEMPORAL_GRPC_WARMUP_SECONDS}s for Temporal "
                "gRPC server to initialise..."
            )
            time.sleep(_TEMPORAL_GRPC_WARMUP_SECONDS)
            console.info("Running Temporal namespace init (one-shot machine)...")
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

            # schema_ok is informational only — Temporal server deploy continues regardless
            _schema_ok = schema_future.result() if schema_future is not None else True

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
                console.info(
                    f"  Waiting {_TEMPORAL_GRPC_WARMUP_SECONDS}s for Temporal "
                    "gRPC server to initialise..."
                )
                time.sleep(_TEMPORAL_GRPC_WARMUP_SECONDS)

                # --- Sequential: namespace-init (must complete before worker starts) ---
                # Running this in parallel with Temporal Web deploy caused flyctl
                # spinner frames from the Web deploy to interleave with health-check
                # output from the machine, making logs unreadable.
                console.print()
                _ns_ok = _run_namespace_init(
                    controller,
                    temporal_app_name,
                    effective_region,
                )

                # --- Sequential: Temporal Web UI (after namespace init, no dependency) ---
                console.print()
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

        console.print()

    # =========================================================================
    # Phase 2: App Setup  (reached for full deploy or --service app)
    # =========================================================================
    console.print_subheader("Phase 2: Main App Setup")
    if not _ensure_app_exists(controller, effective_app, effective_org):
        raise typer.Exit(1)

    # Sync secrets before checking database attachment - DATABASE_URL must
    # already be in Fly secrets for _check_database_attached() to detect it
    if not _sync_secrets(controller, effective_app):
        console.warn("Some secrets may be missing - deployment may fail")

    # Override Docker Compose service hostnames (temporal:7233, redis://redis:…)
    # with Fly.io .internal addresses so the main app can reach its siblings.
    _inject_fly_service_urls(controller, effective_app, effective_app)
    console.print()

    # Check if database is attached to the app
    if not skip_db_check:
        if not _check_database_attached(controller, effective_app):
            console.warn("Database not attached to app!")
            console.info(
                f"  Run: uv run api-forge-cli fly db attach --cluster {cluster_name} --app {effective_app}"
            )
            console.print()

            # Try to attach automatically
            if console.confirm_action(
                "Attach database now",
                f"This will set DATABASE_URL secret on '{effective_app}'",
            ):
                result = controller.mpg_attach(
                    cluster_name,  # type: ignore
                    effective_app,
                )
                if result.success:
                    console.ok("Database attached successfully")
                else:
                    console.error(f"Failed to attach database: {result.stderr}")
                    raise typer.Exit(1)
        else:
            console.ok("Database already attached to app")

    console.print()

    # =========================================================================
    # Phase 3: Configuration
    # =========================================================================
    console.print_subheader("Phase 3: Configuration")

    if _fly_toml_exists() and not regenerate_config:
        console.info("Using existing fly.toml")
    else:
        action = "Regenerating" if _fly_toml_exists() else "Generating"
        console.info(f"{action} fly.toml...")

        _write_fly_toml(
            effective_app,
            effective_region,
            dockerfile=dockerfile,
            overwrite=regenerate_config,
        )
        console.ok(f"fly.toml written to {_get_fly_toml_path()}")

    console.print()

    # =========================================================================
    # Phase 4: Deploy Main Application
    # =========================================================================
    console.print_subheader("Phase 4: Deploy Main Application")
    console.info("Starting deployment...")
    ensure_app_machines_running(effective_app, console=console, controller=controller)

    # cwd=project_root sets the Docker build context so COPY instructions in
    # the Dockerfile resolve correctly.  The dockerfile path itself comes from
    # [build].dockerfile in fly.toml (stored as a toml-relative path ../Dockerfile)
    # so we don't need to pass --dockerfile here.
    result = controller.deploy(
        app=effective_app,
        config=str(_get_fly_toml_path()),
        image=image,
        primary_region=effective_region,
        strategy=strategy,
        no_cache=no_cache,
        cwd=str(get_project_root()),
    )

    if result.success:
        console.print()
        console.ok("Deployment completed successfully!")
        console.print()

        # =====================================================================
        # Phase 5: Post-deployment summary
        # =====================================================================
        console.print_subheader("Phase 5: Deployment Summary")
        console.info(f"🌐 App URL: https://{effective_app}.fly.dev")
        console.print()

        # Show service status table
        table = Table(show_header=True, header_style="bold")
        table.add_column("Service")
        table.add_column("Status")
        table.add_column("Details")

        table.add_row(
            "App",
            "[green]✓ Deployed[/green]",
            f"https://{effective_app}.fly.dev",
        )

        if not skip_db_check and cluster_name:
            table.add_row(
                "PostgreSQL",
                "[green]✓ Connected[/green]",
                f"Cluster: {cluster_name}",
            )

        # Show deployed services
        for service_name, service_app, port in services_deployed:
            table.add_row(
                service_name,
                "[green]✓ Deployed[/green]",
                f"{service_app}.flycast:{port}",
            )

        # Show failed services
        for service_name in services_failed:
            table.add_row(
                service_name,
                "[red]✗ Failed[/red]",
                "Check logs above",
            )

        console.print(table)
        console.print()

        # Show note about Temporal setup if Temporal was deployed
        if any(s[0] == "Temporal" for s in services_deployed):
            console.print("[bold cyan]📝 Temporal Setup Notes:[/bold cyan]")
            console.info(
                "Temporal requires database schema initialization. In k8s, this is handled"
            )
            console.info(
                "by Jobs (temporal-schema-setup, temporal-namespace-init). For Fly.io:"
            )
            console.print()
            console.info(
                "  1. Schema setup runs automatically via Temporal's auto-setup"
            )
            console.info(
                "  2. Access Temporal Web UI: https://{}.fly.dev".format(
                    _generate_service_app_name(effective_app, "temporal-web")
                )
            )
            console.info(
                "  3. Temporal server: {}.flycast:7233 (internal)".format(
                    _generate_service_app_name(effective_app, "temporal")
                )
            )
            console.print()

        console.print_subheader("Useful commands")
        console.info("  Status: uv run api-forge-cli fly status")
        console.info("  Logs:   uv run api-forge-cli fly logs")
        console.info("  Scale:  uv run api-forge-cli fly scale --count 2")

        # Show service-specific URLs
        if services_deployed:
            console.print()
            console.info("Service internal URLs (use .flycast for app-to-app):")
            for service_name, service_app, port in services_deployed:
                console.info(f"  {service_name}: {service_app}.flycast:{port}")
    else:
        console.error("Deployment failed")
        if result.stderr:
            console.print(f"[dim]{result.stderr}[/dim]")
        raise typer.Exit(1)
