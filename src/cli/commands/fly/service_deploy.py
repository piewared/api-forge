"""Fly.io service deployment (Redis, Temporal, Worker, etc.)."""

from src.cli.shared.console import console
from src.infra.docker_compose import DockerComposeParser
from src.infra.flyio import FlyCtlControllerSync
from src.infra.flyio.temporal import inject_temporal_fly_secrets
from src.infra.secrets import SecretKind, get_secrets_manager
from src.utils.paths import get_project_root

from .secrets import _sync_secrets
from .settings import _get_db_cluster_name, _load_env_file
from .toml import _get_fly_dir

# Service specs: (display_name, compose_service_name, port, memory)
SERVICE_SPECS: dict[str, tuple[str, str, int, str]] = {
    "redis": ("Redis", "redis", 6379, "512mb"),
    "temporal": ("Temporal", "temporal", 7233, "1gb"),
    "temporal-web": ("Temporal Web", "temporal-web", 8080, "256mb"),
    "worker": ("Worker", "worker", 8000, "512mb"),
}


def _generate_service_app_name(base_name: str, service: str) -> str:
    """Generate a service app name from the base app name.

    Args:
        base_name: Base app name (e.g., 'my-app')
        service: Service name ('redis', 'temporal', 'temporal-web', 'worker')

    Returns:
        Service app name (e.g., 'my-app-redis')
    """
    return f"{base_name}-{service}"


def _sync_service_secrets(
    controller: FlyCtlControllerSync,
    service_app_name: str,
    secret_files: list[str],
    env_vars: dict[str, str] | None = None,
) -> bool:
    """Sync secrets and env vars to a service app.

    Args:
        controller: FlyCtlControllerSync instance
        service_app_name: Name of the service Fly app
        secret_files: List of secret file names (without .txt extension)
        env_vars: Additional environment variables to set

    Returns:
        True if secrets were synced successfully
    """
    manager = get_secrets_manager()
    secrets_to_set: dict[str, str] = {}

    # Sync secret files
    for secret_name in secret_files:
        env_var = secret_name.upper()
        if manager.exists(secret_name, SecretKind.KEY):
            value = manager.read(secret_name, SecretKind.KEY)
            if value:
                secrets_to_set[env_var] = value.strip()

    # Add additional env vars
    if env_vars:
        secrets_to_set.update(env_vars)

    if not secrets_to_set:
        return True

    # Set secrets on service app
    result = controller.secrets_set(service_app_name, secrets_to_set, stage=True)
    return result.success


def _inject_fly_service_urls(
    controller: FlyCtlControllerSync,
    app_name: str,
    base_app_name: str,
) -> None:
    """Override Docker Compose service hostnames with Fly.io .internal addresses.

    Ports and protocols are derived from config.yaml defaults via
    ``parse_service_defaults`` — never hardcoded here.

    After Phase 1 promotion, only plain keys (TEMPORAL_URL, REDIS_URL)
    are needed; PRODUCTION_* prefixed keys are no longer set.
    """
    from src.app.runtime.config.deployment_targets import (
        parse_service_defaults,
        resolve_fly_service_urls,
    )

    console.info("  Injecting Fly.io service URLs...")
    defaults = parse_service_defaults()
    fly_urls = resolve_fly_service_urls(defaults, base_app_name)
    url_result = controller.secrets_set(app_name, fly_urls, stage=True)
    if not url_result.success:
        console.warn(f"  Failed to set Fly.io service URLs: {url_result.stderr}")


def _check_app_machine_status(
    controller: FlyCtlControllerSync,
    app_name: str,
    *,
    label: str | None = None,
) -> None:
    """Warn if any machines for *app_name* are stopped or suspended.

    Does not raise — Phase 0 is informational only.  The actual waking
    happens in ``_deploy_service_app`` / Phase 4 via
    ``ensure_app_machines_running``.

    Args:
        controller: FlyCtlControllerSync instance.
        app_name:   Fly app name to inspect.
        label:      Display name for log messages (defaults to app_name).
    """
    display = label or app_name
    app_info = controller.app_info(app_name)
    if not app_info:
        console.info(f"  {display}: app not yet created (will be on first deploy)")
        return

    machines = controller.machines_list(app_name)
    if not machines:
        console.info(f"  {display}: no machines provisioned yet")
        return

    _NOT_RUNNING = {"stopped", "suspended", "stopping", "created"}
    not_running = [m for m in machines if m.get("state") in _NOT_RUNNING]
    started = [m for m in machines if m.get("state") == "started"]

    if not not_running:
        console.ok(f"  {display}: {len(started)} machine(s) running")
    else:
        states = ", ".join(
            f"{m.get('id', '?')[:8]}={m.get('state')}" for m in not_running
        )
        console.warn(
            f"  {display}: {len(not_running)} machine(s) are not running ({states}). "
            "They will be woken automatically before deployment."
        )


def _deploy_service_app(
    controller: FlyCtlControllerSync,
    service_name: str,
    service_app_name: str,
    compose_service_name: str,
    region: str,
    org: str | None,
    internal_port: int,
    memory: str = "512mb",
    *,
    base_app_name: str | None = None,
) -> bool:
    """Deploy a service as a separate Fly app using docker-compose.prod.yml config.

    Args:
        controller: FlyCtlControllerSync instance
        service_name: Service display name for logging
        service_app_name: Fly app name for the service
        compose_service_name: Service name in docker-compose.prod.yml
        region: Fly.io region
        org: Organization (optional)
        internal_port: Port the service listens on
        memory: VM memory size (e.g., "512mb", "1gb")
        base_app_name: Base Fly app name used to derive sibling service addresses
            (e.g. "my-app" so temporal is "my-app-temporal"). Required for
            app/worker services that need to reach other Fly services.

    Returns:
        True if deployment succeeded, False otherwise
    """
    console.info(f"Deploying {service_name} service...")

    # Initialize parser for docker-compose.prod.yml (single source of truth)
    compose_file = get_project_root() / "docker-compose.prod.yml"
    parser = DockerComposeParser(compose_file)

    if not parser.service_exists(compose_service_name):
        console.error(
            f"Service '{compose_service_name}' not found in docker-compose.prod.yml"
        )
        return False

    # Check if app exists, create if not
    app_info = controller.app_info(service_app_name)
    if not app_info:
        console.info(f"  Creating app '{service_app_name}'...")
        result = controller.app_create(service_app_name, org=org)
        if not result.success:
            console.error(f"Failed to create {service_name} app: {result.stderr}")
            return False
        console.ok(f"  App '{service_app_name}' created")
    else:
        # Pre-start stopped or suspended machines before deploying.
        # - "stopped"   → fly deploy updates image config but leaves the machine
        #                 stopped; must be started first.
        # - "suspended" → fly deploy updates image config but also leaves the
        #                 machine stopped rather than running; must be started.
        # We issue machine_start and move on immediately (no polling). This lets
        # fly deploy see the machine as starting and do a proper in-place update.
        # NOTE: do NOT use ensure_app_machines_running here — that polls until
        # healthy, which causes fly deploy to treat the now-running machine as a
        # live peer and spin up a second machine alongside it.
        machines = controller.machines_list(service_app_name)
        needs_start = [
            m for m in machines if m.get("state") in ("stopped", "suspended")
        ]
        if needs_start:
            console.info(
                f"  Starting {len(needs_start)} stopped/suspended machine(s) before deploying..."
            )
            for m in needs_start:
                mid = m.get("id", "")
                if mid:
                    controller.machine_start(service_app_name, mid)

    # Get secrets and environment from parser
    key_secrets = parser.get_key_secrets(compose_service_name)
    env_vars = parser.get_resolved_environment(compose_service_name)

    # Sync secrets before deployment.
    # - app / worker: use _sync_secrets (full path) so that PRODUCTION_DATABASE_URL
    #   is promoted to DATABASE_URL, .env vars are synced, hardcoded overrides
    #   (APP_ENVIRONMENT=production) are applied, etc.  These services get their
    #   DB URL from .env in Compose; on Fly.io that file doesn't exist so the
    #   full promotion logic must run.
    # - Other services (redis, temporal, temporal-web): use _sync_service_secrets
    #   (lightweight path) which only handles the secrets: block entries from
    #   docker-compose.prod.yml.
    _APP_LIKE_SERVICES = {"app", "worker"}
    if compose_service_name in _APP_LIKE_SERVICES:
        console.info(f"  Syncing secrets for {service_name}...")
        if not _sync_secrets(controller, service_app_name):
            console.warn(f"  Failed to sync some secrets for {service_name}")

        # Override Docker Compose hostnames with Fly.io .internal addresses.
        # Delegates to _inject_fly_service_urls which derives ports/protocols
        # from config.yaml defaults.
        if base_app_name:
            _inject_fly_service_urls(controller, service_app_name, base_app_name)
    elif key_secrets:
        console.info(f"  Syncing secrets for {service_name}...")
        if not _sync_service_secrets(
            controller, service_app_name, key_secrets, env_vars
        ):
            console.warn(f"  Failed to sync some secrets for {service_name}")

    # Temporal requires extra env var translation that the docker-compose
    # entrypoint scripts perform at runtime (POSTGRES_PWD, POSTGRES_SEEDS, …).
    # On Fly.io those scripts never run — delegate to the infra module which
    # derives and injects the values directly as Fly secrets.
    if compose_service_name == "temporal":
        console.info("  Injecting Temporal-specific Fly.io secrets...")
        inject_temporal_fly_secrets(
            controller,
            service_app_name,
            cluster_name=_get_db_cluster_name(),
            env_lookup=_load_env_file(include_fly_overrides=True),
            console=console,
        )

    # Get Dockerfile path, build context, and image from parser
    build_context = parser.get_build_context(compose_service_name, get_project_root())
    dockerfile_path = parser.get_dockerfile_path(
        compose_service_name, get_project_root()
    )
    image = parser.get_image(compose_service_name)

    if not dockerfile_path and not image:
        console.error(f"No build config or image specified for {compose_service_name}")
        return False

    # Generate fly.toml for the service (written to .fly/ to keep root clean)
    fly_dir = _get_fly_dir()
    fly_dir.mkdir(parents=True, exist_ok=True)
    service_toml_path = fly_dir / f"fly.{service_name.lower()}.toml"

    # Build env section from resolved environment variables.
    # Skip Docker-secrets file-path vars (values like /run/secrets/...) — those
    # paths don't exist on Fly.io; the actual secret is set via key_secrets.
    env_section = f'[env]\n  PORT = "{internal_port}"\n'
    for key, value in env_vars.items():
        if str(value).startswith("/run/secrets/"):
            console.info(
                f"  Skipping Docker secrets path env var {key} (not applicable on Fly.io)"
            )
            continue
        env_section += f'  {key} = "{value}"\n'

    # Build mounts section from named volumes.
    # Fly.io only supports 1 volume per machine — use the first named volume and
    # warn if the service declared more (backups volumes etc. are dropped).
    mounts_section = ""
    volume_mounts = parser.get_named_volumes(compose_service_name)

    if len(volume_mounts) > 1:
        skipped = [f"{s}:{d}" for s, d in volume_mounts[1:]]
        console.warn(
            f"  Fly.io supports only 1 volume per machine. "
            f"Using '{volume_mounts[0][0]}'; skipping: {', '.join(skipped)}"
        )
        volume_mounts = volume_mounts[:1]

    for source, destination in volume_mounts:
        mounts_section += f'''
[[mounts]]
  source = "{source}"
  destination = "{destination}"
'''

    # Classify services upfront — used both for command/process and network sections.
    #
    #   worker           → no inbound connections; connects outbound to temporal/redis only.
    #   temporal, redis  → TCP services; need [[services]] for .flycast DNS routing; must
    #                      stay always-on (gRPC/RESP traffic looks idle to HTTP heuristics).
    #   app, temporal-web→ HTTP services handled by Fly's HTTP proxy ([http_service]).
    _NO_INBOUND_SERVICES = {"worker"}
    _TCP_BACKGROUND_SERVICES = {"temporal", "redis"}
    _ALWAYS_ON_SERVICES = {"redis", "temporal"}

    if compose_service_name in _ALWAYS_ON_SERVICES:
        auto_stop = "off"
        min_machines = 1
    else:
        auto_stop = "suspend"
        min_machines = 0

    # Emit [processes] only for services where the compose `command:` differs
    # from the image's default CMD.  For TCP background services (temporal,
    # redis) the compose command IS the image default — emitting [processes]
    # alongside [[services]] causes flyctl to reject the config with
    # "App configuration is not valid".
    compose_command = parser.get_command(compose_service_name)
    processes_section = (
        f'[processes]\n  app = "{compose_command}"\n'
        if compose_command and compose_service_name not in _TCP_BACKGROUND_SERVICES
        else ""
    )

    # Build the network/service section.
    if compose_service_name in _NO_INBOUND_SERVICES:
        # Worker has no inbound connections; omit all service sections.
        http_service_section = ""
    elif compose_service_name in _TCP_BACKGROUND_SERVICES:
        # TCP services: [[services]] registers the app in Fly's anycast routing
        # table so that <appname>.flycast resolves to a live machine IP.
        # Note: [processes] must NOT appear alongside [[services]] in flyctl —
        # they conflict without explicit process-group linking.
        http_service_section = f"""[[services]]
  internal_port = {internal_port}
  protocol = "tcp"
  auto_stop_machines = "{auto_stop}"
  auto_start_machines = true
  min_machines_running = {min_machines}
"""
    else:
        # HTTP services: use Fly's managed HTTP proxy.
        http_service_section = f"""[http_service]
  internal_port = {internal_port}
  force_https = false
  auto_stop_machines = "{auto_stop}"
  auto_start_machines = true
  min_machines_running = {min_machines}
"""

    # Build the fly.toml.
    # NOTE: dockerfile is intentionally NOT written into [build] — flyctl resolves
    # it relative to the toml file location, which would give the wrong path for
    # tomls in .fly/. Instead, it is passed as an absolute --dockerfile flag below.
    if dockerfile_path and build_context:
        toml_content = f'''# Fly.io configuration for {service_name}
# Config sourced from docker-compose.prod.yml service: {compose_service_name}
app = "{service_app_name}"
primary_region = "{region}"

[build]

{processes_section}
{env_section}
{http_service_section}
[[vm]]
  memory = "{memory}"
  cpu_kind = "shared"
  cpus = 1
{mounts_section}
'''
    else:
        # Use pre-built image (already retrieved from parser)
        toml_content = f'''# Fly.io configuration for {service_name}
# Config sourced from docker-compose.prod.yml service: {compose_service_name}
app = "{service_app_name}"
primary_region = "{region}"

[build]
  image = "{image}"

{processes_section}
{env_section}
{http_service_section}
[[vm]]
  memory = "{memory}"
  cpu_kind = "shared"
  cpus = 1
{mounts_section}
'''

    service_toml_path.write_text(toml_content)
    console.info(f"  Generated {service_toml_path.name} from docker-compose config")

    # Deploy the service.
    # - cwd=build_context: flyctl's working directory becomes the Docker build
    #   context, so COPY/ADD instructions in the Dockerfile resolve correctly.
    # - dockerfile (absolute): passed as --dockerfile flag rather than in the toml
    #   to avoid flyctl resolving it relative to the toml file's directory.
    # - config is an absolute path since CWD is changing.
    console.info(f"  Deploying {service_name}...")
    result = controller.deploy(
        app=service_app_name,
        config=str(service_toml_path.resolve()),
        dockerfile=str(dockerfile_path.resolve()) if dockerfile_path else None,
        primary_region=region,
        cwd=str(build_context) if build_context else None,
    )

    if result.success:
        console.ok(f"  {service_name} deployed successfully")
        return True
    else:
        console.error(f"  {service_name} deployment failed: {result.stderr}")
        return False
