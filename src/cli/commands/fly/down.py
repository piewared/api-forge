"""Fly.io 'down' command — stop or destroy deployment machines."""

from typing import Annotated

import typer

from src.cli.shared.console import console, with_error_handling
from src.cli.shared.fly import check_prerequisites, get_fly_controller
from src.infra.flyio.controller import FlyCtlControllerSync

from . import fly_app
from .service_deploy import SERVICE_SPECS, _generate_service_app_name
from .settings import _get_app_name, _load_fly_app_settings
from .toml import _fly_toml_exists, _get_fly_toml_path

# Human-readable names for the special "main" target
_MAIN_DISPLAY = "Main App"


def _stop_app_machines(
    controller: FlyCtlControllerSync,
    app_name: str,
    display_name: str,
) -> tuple[int, int]:
    """Stop all running machines for a Fly.io app.

    Returns:
        (stopped_count, failed_count)
    """
    machines = controller.machines_list(app_name)
    if not machines:
        console.info(f"  {display_name} ({app_name}): no machines found")
        return 0, 0

    stopped = 0
    failed = 0
    for machine in machines:
        machine_id: str = machine.get("id", "")
        state: str = machine.get("state", "")
        short_id = machine_id[:8]

        if state not in ("started", "starting"):
            console.info(
                f"  {display_name}: machine {short_id} already {state}, skipping"
            )
            continue

        result = controller.machine_stop(app_name, machine_id)
        if result.success:
            console.ok(f"  {display_name}: machine {short_id} stopped")
            stopped += 1
        else:
            console.error(f"  {display_name}: failed to stop machine {short_id}")
            failed += 1

    return stopped, failed


def _destroy_app(
    controller: FlyCtlControllerSync,
    app_name: str,
    display_name: str,
) -> bool:
    """Destroy a Fly.io app completely.

    Returns:
        True if the app was destroyed (or did not exist), False on error.
    """
    app_info = controller.app_info(app_name)
    if not app_info:
        console.info(f"  {display_name} ({app_name}): not found, skipping")
        return True

    result = controller.app_destroy(app_name, confirm=True)
    if result.success:
        console.ok(f"  {display_name} ({app_name}): destroyed")
        return True

    console.error(f"  {display_name} ({app_name}): failed to destroy")
    if result.stderr:
        console.info(f"    {result.stderr}")
    return False


def _build_targets(
    effective_app: str,
    service: str | None,
) -> list[tuple[str, str]]:
    """Return list of (display_name, app_name) pairs to act on."""
    if service is None:
        # All apps: main + every service
        targets: list[tuple[str, str]] = [(_MAIN_DISPLAY, effective_app)]
        for svc_key, (display_name, *_rest) in SERVICE_SPECS.items():
            svc_app = _generate_service_app_name(effective_app, svc_key)
            targets.append((display_name, svc_app))
        return targets

    if service == "main":
        return [(_MAIN_DISPLAY, effective_app)]

    if service not in SERVICE_SPECS:
        console.error(
            f"Unknown service '{service}'. "
            f"Valid options: main, {', '.join(SERVICE_SPECS)}"
        )
        raise typer.Exit(1)

    display_name = SERVICE_SPECS[service][0]
    return [(display_name, _generate_service_app_name(effective_app, service))]


@fly_app.command()
@with_error_handling
def down(
    app: Annotated[
        str | None,
        typer.Option(
            "--app",
            "-a",
            help="App name (from config if not specified)",
        ),
    ] = None,
    service: Annotated[
        str | None,
        typer.Option(
            "--service",
            "-s",
            help=(
                "Scope to a single service: main, "
                + ", ".join(SERVICE_SPECS)
                + "  (default: all)"
            ),
        ),
    ] = None,
    destroy: Annotated[
        bool,
        typer.Option(
            "--destroy",
            help="Permanently destroy apps instead of just stopping their machines",
        ),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip confirmation prompt",
        ),
    ] = False,
    keep_config: Annotated[
        bool,
        typer.Option(
            "--keep-config",
            help="Keep fly.toml after --destroy (no effect without --destroy)",
        ),
    ] = False,
) -> None:
    """Stop or destroy Fly.io deployment machines.

    By default stops all running machines across every deployed app (reversible).
    Pass --destroy to permanently delete all apps and volumes.

    Examples:
        uv run api-forge-cli fly down                       # Stop all machines
        uv run api-forge-cli fly down --service redis       # Stop Redis only
        uv run api-forge-cli fly down --destroy             # Destroy everything
        uv run api-forge-cli fly down --destroy --service worker -y
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    settings = _load_fly_app_settings()
    effective_app = _get_app_name(app, settings)

    if destroy:
        console.print_header("Destroy Fly.io Deployment", style="red")
    else:
        console.print_header("Stop Fly.io Machines")

    targets = _build_targets(effective_app, service)

    target_names = ", ".join(name for name, _ in targets)
    console.info(f"Main app : {effective_app}")
    console.info(
        f"Action   : {'destroy apps permanently' if destroy else 'stop running machines'}"
    )
    console.info(f"Targets  : {target_names}")
    console.print()

    # --- Confirmation ---
    if not yes:
        if destroy:
            details = (
                "This will:\n"
                "  • Delete all machines\n"
                "  • Delete all volumes\n"
                "  • Delete all secrets\n"
                "  • Remove the apps completely"
                + ("" if keep_config else "\n  • Remove fly.toml")
            )
            action_label = f"DESTROY: {target_names}"
            extra_warn: str | None = "This action cannot be undone!"
        else:
            details = "Running machines will be stopped. Use 'fly up' to redeploy."
            action_label = f"Stop machines for: {target_names}"
            extra_warn = None

        if not console.confirm_action(action_label, details, extra_warning=extra_warn):
            console.info("Operation cancelled")
            raise typer.Exit(0)

    console.print()

    # --- Execute ---
    if destroy:
        total_ok = 0
        total_fail = 0
        for display_name, app_name in targets:
            if _destroy_app(controller, app_name, display_name):
                total_ok += 1
            else:
                total_fail += 1

        console.print()
        if total_fail == 0:
            console.ok(f"All {total_ok} app(s) destroyed successfully")
            # Remove fly.toml only on full teardown (no specific service scoped)
            if not keep_config and service is None and _fly_toml_exists():
                _get_fly_toml_path().unlink()
                console.ok("fly.toml removed")
        else:
            console.warn(
                f"{total_ok} destroyed, {total_fail} failed — check output above"
            )
            raise typer.Exit(1)
    else:
        total_stopped = 0
        total_failed = 0
        for display_name, app_name in targets:
            stopped, failed = _stop_app_machines(controller, app_name, display_name)
            total_stopped += stopped
            total_failed += failed

        console.print()
        if total_failed == 0:
            if total_stopped == 0:
                console.info("No running machines found — nothing to stop")
            else:
                console.ok(f"{total_stopped} machine(s) stopped")
            console.info("Tip: Run 'uv run api-forge-cli fly up' to redeploy")
        else:
            console.warn(
                f"{total_stopped} stopped, {total_failed} failed — check output above"
            )
            raise typer.Exit(1)
