"""Fly.io app creation and deployment prerequisite checks."""

from hashlib import md5

import typer

from src.cli.shared.console import console
from src.infra.flyio import FlyCtlControllerSync
from src.infra.flyio.port_forward import ensure_app_machines_running

from .settings import _get_db_cluster_name


def _ensure_app_exists(
    controller: FlyCtlControllerSync,
    app_name: str,
    org: str | None,
) -> bool:
    """Ensure the Fly.io app exists, creating it if necessary.

    Args:
        controller: FlyCtlControllerSync instance
        app_name: Name of the app
        org: Organization (optional)

    Returns:
        True if app exists or was created, False on failure
    """
    # Check if app already exists
    existing = controller.app_info(app_name)
    if existing:
        console.debug(f"App '{app_name}' already exists")
        return True

    # Create the app
    console.info(f"Creating app '{app_name}'...")
    result = controller.app_create(app_name, org=org)

    if result.success:
        console.ok(f"App '{app_name}' created")
        return True
    else:
        # Check if it's a "name already taken" error
        if result.stderr and "already been taken" in result.stderr:
            console.error(f"App name '{app_name}' is already taken globally.")
            console.print()
            console.info("Fly.io app names must be globally unique. Try one of:")
            console.info(
                f"  1. Generate unique name: uv run api-forge-cli fly up --app my-unique-app-{md5(app_name.encode()).hexdigest()[:6]}"
            )
            console.info("  2. Set a custom name in config.yaml:")
            console.info("     deployments:")
            console.info("       fly_io:")
            console.info("         app:")
            console.info("           name: my-unique-app-name")
            console.info("  3. Let the CLI auto-generate a name based on your project")
            console.print()
            console.info("Checking your existing apps...")
            apps = controller.apps_list(org=org)
            if apps:
                console.info(f"You have {len(apps)} existing app(s):")
                for existing_app in apps[:5]:  # Show first 5
                    console.info(f"  - {existing_app.name}")
                if len(apps) > 5:
                    console.info(f"  ... and {len(apps) - 5} more")
        else:
            console.error(f"Failed to create app: {result.stderr}")
        return False


def _check_database_exists(controller: FlyCtlControllerSync) -> tuple[bool, str | None]:
    """Check if the configured Fly Postgres database exists and warn if suspended.

    Checks both managed postgres (mpg) and legacy/unmanaged postgres apps.
    When the cluster is found but its machines are stopped or suspended, a
    warning is printed — the cluster exists, but queries will fail until the
    machines wake up.  For Fly MPG the machines wake automatically on first
    connection; for legacy apps ``ensure_app_machines_running`` handles it.

    Returns:
        Tuple of (exists, cluster_name)
    """
    _NOT_RUNNING = {"stopped", "suspended", "stopping", "created"}

    cluster_name = _get_db_cluster_name()
    if not cluster_name:
        return False, None

    # Check managed postgres first
    mpg_info = controller.mpg_status(cluster_name)
    if mpg_info:
        # MPG exposes a cluster-level status field.
        if mpg_info.status and mpg_info.status.lower() not in ("ready", "running", ""):
            console.warn(
                f"  Database cluster '{cluster_name}' status: {mpg_info.status}. "
                "It may be suspended or starting up — connections could be slow or "
                "unavailable until machines are fully awake."
            )
        else:
            # Also cross-check individual machines (MPG exposes them as a Fly app).
            machines = controller.machines_list(cluster_name)
            not_running = [m for m in machines if m.get("state") in _NOT_RUNNING]
            if not_running:
                states = ", ".join(
                    f"{m.get('id', '?')[:8]}={m.get('state')}" for m in not_running
                )
                console.warn(
                    f"  Database '{cluster_name}': {len(not_running)} machine(s) are "
                    f"not running ({states}). Fly MPG wakes them automatically on "
                    "first connection, but the initial query may time out."
                )
        return True, cluster_name

    # Check legacy/unmanaged postgres apps
    legacy_clusters = controller.postgres_list()
    for legacy in legacy_clusters:
        if legacy.name == cluster_name:
            # For legacy apps check individual machine states.
            machines = controller.machines_list(cluster_name)
            not_running = [m for m in machines if m.get("state") in _NOT_RUNNING]
            if not_running:
                states = ", ".join(
                    f"{m.get('id', '?')[:8]}={m.get('state')}" for m in not_running
                )
                console.warn(
                    f"  Database '{cluster_name}': {len(not_running)} machine(s) are "
                    f"stopped or suspended ({states})."
                )
                console.info(
                    "  Unlike Fly MPG, legacy Postgres apps do not wake automatically."
                )
                if not console.confirm_action(
                    f"Start {len(not_running)} database machine(s) now",
                    f"This will run `fly machines start` for each stopped machine "
                    f"in '{cluster_name}' before continuing.",
                ):
                    console.error(
                        "Deployment cancelled — database machines must be running "
                        "before deploying. Start them manually with:\n"
                        f"  fly machines start --app {cluster_name}"
                    )
                    raise typer.Exit(1)

                # Start each stopped machine and wait for them to come up.
                for machine in not_running:
                    machine_id = machine.get("id", "")
                    if machine_id:
                        console.info(f"  Starting machine {machine_id[:8]}...")
                        result = controller.machine_start(cluster_name, machine_id)
                        if not result.success:
                            console.warn(
                                f"  Failed to start machine {machine_id[:8]}: "
                                f"{result.stderr}"
                            )

                ensure_app_machines_running(
                    cluster_name, console=console, controller=controller
                )

            return True, cluster_name

    return False, cluster_name


def _check_database_attached(
    controller: FlyCtlControllerSync,
    app_name: str,
) -> bool:
    """Check if DATABASE_URL secret is set on the app (indicating DB is attached).

    Args:
        controller: FlyCtlControllerSync instance
        app_name: Name of the Fly.io app

    Returns:
        True if DATABASE_URL is set
    """
    secrets = controller.secrets_list(app_name)
    return "DATABASE_URL" in secrets
