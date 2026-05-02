"""Shared "deploy the main app" pipeline used by both ``fly up`` and ``fly sync``.

Both commands need the same sequence of steps to ship the main application
image to Fly.io:

  1. Ensure the Fly app exists.
  2. Sync secrets (so DATABASE_URL is present for the attachment check).
  3. Inject sibling service URLs so the app can reach Redis / Temporal.
  4. Verify the database is attached (offer to attach interactively if not).
  5. Generate or reuse ``fly.toml``.
  6. Wake any stopped machines.
  7. Run ``fly deploy``.

The work is identical between commands; only the framing differs (``up`` is
preceded by a multi-app pre-flight + supporting-services phase, ``sync`` is
preceded by a single main-app machine probe). Putting it in one helper avoids
the two commands drifting apart.
"""

from __future__ import annotations

import typer

from src.cli.shared.console import console
from src.infra.flyio.controller import CommandResult, FlyCtlControllerSync
from src.infra.flyio.port_forward import ensure_app_machines_running
from src.utils.paths import get_project_root

from .deploy import _check_database_attached, _ensure_app_exists
from .secrets import _sync_secrets
from .service_deploy import _inject_fly_service_urls
from .toml import _fly_toml_exists, _get_fly_toml_path, _write_fly_toml


def deploy_main_app(
    controller: FlyCtlControllerSync,
    *,
    effective_app: str,
    effective_region: str,
    effective_org: str | None,
    cluster_name: str | None,
    dockerfile: str = "Dockerfile",
    image: str | None = None,
    strategy: str | None = None,
    no_cache: bool = False,
    regenerate_config: bool = False,
    skip_db_check: bool = False,
) -> CommandResult:
    """Run the main-app deploy pipeline. Returns the ``fly deploy`` result.

    Raises ``typer.Exit`` when prerequisites can't be satisfied (app cannot be
    created, user declines DB attachment, etc.).
    """
    # 1. App must exist
    if not _ensure_app_exists(controller, effective_app, effective_org):
        raise typer.Exit(1)

    # 2. Sync secrets first — DATABASE_URL must be staged before
    # _check_database_attached() can detect it.
    if not _sync_secrets(controller, effective_app):
        console.warn("Some secrets may be missing - deployment may fail")

    # 3. Override Docker Compose service hostnames (temporal:7233, redis://redis:…)
    # with Fly.io .internal addresses so the main app can reach its siblings.
    _inject_fly_service_urls(controller, effective_app, effective_app)

    # 4. Database attachment check
    if not skip_db_check:
        if not _check_database_attached(controller, effective_app):
            console.warn("Database not attached to app")
            console.print(
                f"  Run: uv run api-forge-cli fly db attach "
                f"--cluster {cluster_name} --app {effective_app}"
            )
            console.print()

            if console.confirm_action(
                "Attach database now",
                f"This will set DATABASE_URL secret on '{effective_app}'",
            ):
                attach_result = controller.mpg_attach(
                    cluster_name,  # type: ignore[arg-type]
                    effective_app,
                )
                if attach_result.success:
                    console.ok("Database attached successfully")
                else:
                    console.error(f"Failed to attach database: {attach_result.stderr}")
                    raise typer.Exit(1)
        else:
            console.ok("Database already attached")

    # 5. fly.toml — regenerate only when forced or missing
    if _fly_toml_exists() and not regenerate_config:
        console.debug("Using existing fly.toml")
    else:
        action = "Regenerating" if _fly_toml_exists() else "Generating"
        console.step(f"{action} fly.toml...")
        _write_fly_toml(
            effective_app,
            effective_region,
            dockerfile=dockerfile,
            overwrite=regenerate_config,
        )
        console.ok(f"fly.toml written to {_get_fly_toml_path()}")

    # 6. Wake stopped/suspended machines so flyctl does an in-place update
    # rather than provisioning new peers alongside dead ones.
    console.step("Starting deployment...")
    ensure_app_machines_running(effective_app, console=console, controller=controller)

    # 7. Deploy. cwd=project_root sets the Docker build context so COPY
    # instructions in the Dockerfile resolve correctly. The dockerfile path
    # itself comes from [build].dockerfile in fly.toml.
    return controller.deploy(
        app=effective_app,
        config=str(_get_fly_toml_path()),
        image=image,
        primary_region=effective_region,
        strategy=strategy,
        no_cache=no_cache,
        cwd=str(get_project_root()),
    )
