"""Fly.io deployment helpers for the Temporal workflow engine.

Handles the environment variable translation that the docker-compose
``universal-entrypoint.sh`` + ``entrypoint.sh`` scripts perform at container
startup — work that never happens on Fly.io because those scripts are
volume-mounted and not baked into the image.

Callers supply the data they already hold (cluster name, .env vars) so this
module has no dependency on CLI config loaders or the file system.
"""

from typing import Any

from src.infra.flyio import FlyCtlControllerSync
from src.infra.flyio.url_utils import extract_pg_host_port
from src.infra.secrets import SecretKind, get_secrets_manager

# Docker image that bundles temporal-sql-tool (same tag used in docker-compose)
_ADMIN_TOOLS_IMAGE = "temporalio/admin-tools:1.29.0-tctl-1.18.4-cli-1.4.2"

# Substrings that mark an unusable host value in DATABASE_URL — placeholder
# secrets, generic templating, or local addresses that won't resolve from a
# Fly machine. Used by ``_resolve_pg_host_port``.
_UNUSABLE_HOST_HINTS = ("CHANGE_ME", "your-", "localhost", "127.0.0.1", "::1")


def _resolve_pg_host_port(
    controller: FlyCtlControllerSync,
    env_lookup: dict[str, str],
    cluster_name: str | None,
) -> tuple[str, str] | None:
    """Resolve the postgres ``(host, port)`` for Temporal Fly deployments.

    Tries, in order:
    1. ``PRODUCTION_DATABASE_URL`` / ``DATABASE_URL`` from ``.env`` (skipping
       known placeholder/local values).
    2. A live ``fly mpg connection-string <cluster>`` call (only when
       ``cluster_name`` is provided).

    Returns ``None`` if no usable host could be derived; callers translate
    that into the appropriate user-visible warning.
    """
    for key in ("PRODUCTION_DATABASE_URL", "DATABASE_URL"):
        raw = env_lookup.get(key, "").strip()
        if raw and not any(s in raw for s in _UNUSABLE_HOST_HINTS):
            host_port = extract_pg_host_port(raw)
            if host_port:
                return host_port

    if cluster_name:
        ok, conn_str = controller.mpg_connection_string(cluster_name)
        if ok and conn_str:
            return extract_pg_host_port(conn_str)

    return None


def _emit(console: Any, level: str, msg: str) -> None:
    """Write a log message through an optional console object.

    Falls back to ``print`` when no console is provided, so this module is
    usable outside the CLI (e.g., in tests).

    Args:
        console: Object with ``ok``/``warn``/``info`` methods, or ``None``.
        level:   Method name to call on the console (``"ok"``, ``"warn"``, …).
        msg:     Message text.
    """
    if console is None:
        print(msg)
        return
    fn = getattr(console, level, None) or getattr(console, "print", print)
    if fn:
        fn(msg)


def inject_temporal_fly_secrets(
    controller: FlyCtlControllerSync,
    app_name: str,
    *,
    cluster_name: str | None,
    env_lookup: dict[str, str],
    console: Any = None,
) -> None:
    """Derive and inject env vars that the docker-compose entrypoints supply at runtime.

    In docker-compose and Kubernetes, two scripts run before Temporal starts:

    - ``universal-entrypoint.sh`` — reads ``/run/secrets/postgres_temporal_pw``
      and exports ``POSTGRES_TEMPORAL_PW``
    - ``entrypoint.sh`` — maps ``POSTGRES_TEMPORAL_PW`` → ``POSTGRES_PWD`` and
      parses ``PRODUCTION_DATABASE_URL`` → ``POSTGRES_SEEDS`` / ``SQL_HOST_NAME``
      / ``DB_PORT``

    On Fly.io those scripts are never executed, so the Temporal binary receives
    none of these variables and fails to connect (``[::1]:5432 refused``).  This
    function replicates the same derivation and writes the results as Fly secrets
    (which take precedence over ``[env]`` in ``fly.toml``).

    Args:
        controller:   A ``FlyCtlControllerSync`` instance (typed ``Any`` to
                      avoid a circular import; callers pass the real object).
        app_name:     Fly app name for the Temporal service.
        cluster_name: Fly Managed Postgres cluster name (from config), or
                      ``None`` if not configured.
        env_lookup:   Resolved ``.env`` key/value pairs.  Used to extract
                      ``PRODUCTION_DATABASE_URL`` / ``DATABASE_URL`` before
                      falling back to a live ``mpg connection-string`` call.
        console:      Optional object with ``ok``/``warn``/``info`` methods for
                      status output.
    """
    manager = get_secrets_manager()
    secrets: dict[str, str] = {}

    # -------------------------------------------------------------------------
    # 1. POSTGRES_PWD
    # Temporal reads POSTGRES_PWD.  The docker-compose entrypoint does:
    #   export POSTGRES_PWD="$POSTGRES_TEMPORAL_PW"
    # The raw secret is already synced under POSTGRES_TEMPORAL_PW, but Temporal
    # won't find it under that name — set POSTGRES_PWD explicitly.
    # -------------------------------------------------------------------------
    pw_value = manager.read("postgres_temporal_pw", SecretKind.KEY)
    if pw_value:
        secrets["POSTGRES_PWD"] = pw_value.strip()
        _emit(console, "debug", "Set POSTGRES_PWD from postgres_temporal_pw")
    else:
        _emit(
            console,
            "warn",
            "postgres_temporal_pw not found; POSTGRES_PWD will not be set",
        )

    # -------------------------------------------------------------------------
    # 2. POSTGRES_SEEDS / SQL_HOST_NAME / DB_PORT
    # The docker-compose entrypoint parses these from PRODUCTION_DATABASE_URL.
    # ``_resolve_pg_host_port`` checks .env first, then falls back to a live
    # ``fly mpg connection-string`` call.
    # -------------------------------------------------------------------------
    host_port = _resolve_pg_host_port(controller, env_lookup, cluster_name)

    if host_port:
        pg_host, pg_port = host_port
        secrets["POSTGRES_SEEDS"] = pg_host
        secrets["SQL_HOST_NAME"] = pg_host
        secrets["DB_PORT"] = pg_port
        _emit(console, "debug", f"Set POSTGRES_SEEDS={pg_host} port={pg_port}")
    elif cluster_name:
        _emit(
            console,
            "warn",
            f"Could not resolve postgres host for cluster '{cluster_name}'; "
            "POSTGRES_SEEDS not set",
        )
    else:
        _emit(
            console,
            "warn",
            "No database cluster configured; POSTGRES_SEEDS not set.\n"
            "  Set deployments.fly_io.database.name so Temporal can reach postgres.",
        )

    # -------------------------------------------------------------------------
    # 3. Disable cert-based TLS
    # Fly.io's private WireGuard network handles transport security.  The
    # docker-compose cert paths (/tmp/certs/ca-bundle.crt) do not exist on Fly
    # machines, so cert verification must be turned off for internal connections.
    # -------------------------------------------------------------------------
    secrets["SQL_TLS_ENABLED"] = "false"
    secrets["SQL_HOST_VERIFICATION"] = "false"
    _emit(console, "debug", "Set SQL_TLS_ENABLED=false (Fly private WireGuard network)")

    if secrets:
        result = controller.secrets_set(app_name, secrets, stage=True)
        if not result.success:
            _emit(
                console,
                "warn",
                f"  Failed to set Temporal Fly.io secrets: {result.stderr}",
            )


def run_temporal_schema_setup(
    controller: FlyCtlControllerSync,
    *,
    temporal_app_name: str,
    cluster_name: str | None,
    env_lookup: dict[str, str],
    region: str | None = None,
    temporal_db: str = "temporal",
    temporal_vis_db: str = "temporal_visibility",
    temporal_db_user: str = "temporaluser",
    console: Any = None,
) -> bool:
    """Run the Temporal schema setup job on Fly.io.

    Replicates the ``temporal-schema-setup`` docker-compose service: spins up a
    one-shot ``temporalio/admin-tools`` machine on the same Fly app (so it
    inherits the app's secrets), runs ``temporal-sql-tool`` against both the
    main and visibility databases, then destroys the machine.

    Args:
        controller:         ``FlyCtlControllerSync`` instance.
        temporal_app_name:  Fly app name for the Temporal server.
        cluster_name:       Fly MPG cluster name (used to resolve the DB host).
        env_lookup:         Resolved ``.env`` key/value pairs.
        region:             Fly region; defaults to app's primary region.
        temporal_db:        Main Temporal database name.
        temporal_vis_db:    Temporal visibility database name.
        temporal_db_user:   Postgres user for Temporal.
        console:            Optional console for status output.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    host_port = _resolve_pg_host_port(controller, env_lookup, cluster_name)
    if not host_port:
        _emit(
            console,
            "error",
            "  Cannot run schema setup: postgres host could not be determined.\n"
            "  Ensure PRODUCTION_DATABASE_URL is set in .env or configure "
            "deployments.fly_io.database.name in config.yaml.",
        )
        return False

    pg_host, pg_port = host_port

    # ------------------------------------------------------------------
    # Read temporal postgres password from local secrets
    # ------------------------------------------------------------------
    manager = get_secrets_manager()
    pw_value = manager.read("postgres_temporal_pw", SecretKind.KEY)
    if not pw_value:
        _emit(
            console,
            "error",
            "  postgres_temporal_pw secret not found; cannot run schema setup.",
        )
        return False

    pw = pw_value.strip()

    # ------------------------------------------------------------------
    # Build the shell command — inlines the essential logic of schema-setup.sh
    # so there is no dependency on a volume-mounted script file.
    # TLS is disabled: the machine talks to Fly MPG over WireGuard.
    # PGPASSWORD is passed via the machine env block (below) rather than
    # interpolated into the shell command — passwords containing a single
    # quote would otherwise break out of the surrounding shell quoting.
    # ------------------------------------------------------------------
    setup_cmd = (
        "set -e; "
        "run_sql() { "
        f"  temporal-sql-tool --plugin postgres12 --ep {pg_host} -p {pg_port} "
        f'  -u {temporal_db_user} -pw "$PGPASSWORD" --db "$1" --tls=false $2; '
        "}; "
        f"run_sql {temporal_db} 'setup-schema -v 0.0' || true; "
        f"run_sql {temporal_db} 'update-schema --schema-name postgresql/v12/temporal'; "
        f"run_sql {temporal_vis_db} 'setup-schema -v 0.0' || true; "
        f"run_sql {temporal_vis_db} 'update-schema --schema-name postgresql/v12/visibility'; "
        "echo 'Schema setup complete.'"
    )

    env = {
        "TEMPORAL_DB": temporal_db,
        "TEMPORAL_VIS_DB": temporal_vis_db,
        "TEMPORAL_DB_USER": temporal_db_user,
        "PGPASSWORD": pw,
    }

    _emit(console, "debug", f"Connecting to postgres host: {pg_host}:{pg_port}")

    # ------------------------------------------------------------------
    # Retry strategy
    # ``fly machine run`` waits up to 5 minutes for the machine to reach
    # ``started`` and exposes no flag to extend that. Cold pulls of the
    # 202 MB admin-tools image regularly push past it on the first run.
    # By the second run the image is cached on the Fly host, so the
    # machine starts in seconds and the migration completes immediately.
    # ``update-schema`` is idempotent (no-op when the schema is current),
    # so the retry is also safe in the rarer case of a real SQL error
    # — the user just sees the failure twice.
    # ------------------------------------------------------------------
    max_attempts = 2
    last_result = None
    for attempt in range(1, max_attempts + 1):
        if attempt == 1:
            _emit(
                console,
                "debug",
                "Starting one-shot admin-tools machine (streaming output below)...",
            )
        else:
            _emit(
                console,
                "info",
                f"  First attempt failed (likely cold image pull > 5min flyctl wait). "
                f"Retrying ({attempt}/{max_attempts}) — image should now be cached...",
            )

        last_result = controller.machine_run(
            _ADMIN_TOOLS_IMAGE,
            app_name=temporal_app_name,
            # Override both ENTRYPOINT and CMD so the image's default
            # `tini -- sleep infinity` is fully displaced.
            # Without --entrypoint, flyctl appends our args to `sleep infinity`
            # instead of replacing the CMD.
            entrypoint="/bin/sh",
            command=["-c", setup_cmd],
            env=env,
            region=region,
            rm=True,
            # capture_output=False (default) is required: fly machine run needs
            # a TTY-capable stdout to attach to the one-shot machine's console.
            # With capture_output=True (piped stdout) flyctl detects non-TTY
            # mode and exits immediately with "machine failed to reach desired
            # start state" before the container even runs.
            # Subprocess timeout = flyctl's 5 min wait + headroom for the SQL.
            timeout=600,
        )

        if last_result.success:
            if attempt > 1:
                _emit(
                    console,
                    "ok",
                    f"Temporal schema setup complete (attempt {attempt}/{max_attempts})",
                )
            else:
                _emit(console, "ok", "Temporal schema setup complete")
            return True

    # All attempts exhausted.
    # capture_output=False means stderr is streamed to the terminal but not
    # into result.stderr — so the captured value is almost always empty. Point
    # the user at the canonical place to find what actually went wrong, plus
    # the rerun escape hatch. The caller (up.py summary) supplies the broader
    # "this is benign on a pre-initialised DB" framing.
    stderr = (
        last_result.stderr.strip()
        if last_result is not None and last_result.stderr
        else ""
    )
    msg = f"Temporal schema setup failed after {max_attempts} attempts."
    if stderr:
        msg += f"\n  {stderr}"
    msg += (
        f"\n  Inspect logs: fly logs --app {temporal_app_name}"
        "\n  Rerun:        uv run api-forge-cli fly up"
    )
    _emit(console, "error", msg)
    return False


def run_temporal_namespace_init(
    controller: FlyCtlControllerSync,
    *,
    temporal_app_name: str,
    region: str | None = None,
    namespace: str = "default",
    retention: str = "7d",
    console: Any = None,
) -> bool:
    """Ensure a Temporal namespace exists on the Fly.io deployment.

    Replicates the ``temporal-namespace-init`` docker-compose service: spins up
    a one-shot ``temporalio/admin-tools`` machine on the Temporal Fly app (so
    it shares the 6PN private network with the running Temporal server), waits
    for the cluster to be healthy, then creates the namespace if it does not
    already exist.

    The machine uses the ``<temporal_app_name>.internal`` DNS name which
    resolves without any ``[[services]]`` configuration — direct 6PN lookup.

    Args:
        controller:         ``FlyCtlControllerSync`` instance.
        temporal_app_name:  Fly app name for the Temporal server.
        region:             Fly region; defaults to the app's primary region.
        namespace:          Temporal namespace name (default: ``"default"``).
        retention:          Workflow history retention (default: ``"7d"``).
        console:            Optional console for status output.

    Returns:
        ``True`` on success or if the namespace already exists, ``False`` on
        unrecoverable failure.
    """
    # The machine runs *on* the temporal app, so it shares 6PN with the server.
    # .internal resolves to the running machine's IPv6 without requiring
    # [[services]] in fly.toml.
    temporal_address = f"{temporal_app_name}.internal:7233"

    # Inline the essential logic of namespace-init.sh:
    # 1. Wait up to 200 s for the cluster to be healthy (20 retries × 5 s sleep).
    # 2. Fail explicitly if the cluster never became healthy.
    # 3. Create the namespace if it doesn't already exist.
    #
    # Health check uses `tctl` (not `temporal` CLI) because `tctl` is the only
    # binary in the admin-tools image that reliably honours --command-timeout.
    # The `temporal` CLI v1.x does NOT support --command-timeout; without it,
    # each gRPC call can block for 60 s+ on an unresponsive server, making the
    # loop blow past any subprocess timeout.
    #
    # Belt-and-suspenders: wrap every `tctl` invocation in Unix `timeout 8`
    # so a stuck gRPC call is killed by the OS regardless of CLI flag support.
    #
    # Subprocess timeout (360 s) = 200 s health loop + ~160 s machine
    # boot / image pull / namespace create headroom.
    _emit(console, "debug", f"Target address: {temporal_address}")
    _emit(
        console,
        "debug",
        "Launching one-shot admin-tools machine (capturing output)...",
    )

    # Health check strategy:
    # - Use `tctl cluster health` (v1.18.4) — supports --command-timeout
    # - Wrap with Unix `timeout 8` as OS-level hard backstop
    # - Do NOT redirect stderr to /dev/null so tctl errors appear in captured output
    # - Use HEALTHY flag to detect loop exhaustion and fail explicitly
    #
    # capture_output=False (default) is required: see schema setup comment above.
    #
    # Timing budget (360 s subprocess timeout):
    #   20 retries x (8 s tctl max + 5 s sleep) = 260 s worst case health wait
    #   + ~100 s headroom for machine boot, image pull, and namespace create
    init_cmd = (
        "set -e; "
        "echo '--- Temporal namespace init ---'; "
        "echo 'address: " + temporal_address + "'; "
        "HEALTHY=0; "
        "for i in $(seq 1 20); do "
        f'  echo "health check attempt $i/20..."; '
        f"  if timeout 8 tctl --address {temporal_address} --command-timeout 6s cluster health; then "
        "    HEALTHY=1; break; "
        "  fi; "
        "  echo 'not ready, retrying in 5s...'; "
        "  sleep 5; "
        "done; "
        'if [ "$HEALTHY" -ne 1 ]; then '
        "  echo 'ERROR: Temporal cluster did not become healthy after 20 attempts'; "
        "  exit 1; "
        "fi; "
        "echo 'cluster healthy'; "
        f"if timeout 15 temporal --address {temporal_address} "
        f"   operator namespace describe -n {namespace} >/dev/null 2>&1; then "
        "  echo 'namespace already exists — nothing to do'; "
        "else "
        "  echo 'creating namespace...'; "
        f"  timeout 30 temporal --address {temporal_address} "
        f"  operator namespace create -n {namespace} --retention {retention}; "
        "  echo 'namespace created'; "
        "fi"
    )

    result = controller.machine_run(
        _ADMIN_TOOLS_IMAGE,
        app_name=temporal_app_name,
        # Override ENTRYPOINT so the image's default `tini -- sleep infinity`
        # is fully replaced by our shell command.
        entrypoint="/bin/sh",
        command=["-c", init_cmd],
        env={"TEMPORAL_ADDRESS": temporal_address},
        region=region,
        rm=True,
        # The admin-tools image is cached at this point (schema-setup ran
        # first), so flyctl's hardcoded 5 min wait is plenty. Subprocess
        # timeout (600 s) absorbs the 200 s health-check loop plus headroom.
        timeout=600,
        # capture_output=False (default): fly machine run needs TTY-capable
        # stdout. See schema setup comment for details.
    )

    if result.success:
        _emit(console, "ok", "Temporal namespace init complete")
        return True
    else:
        stderr = (
            result.stderr.strip()
            if result.stderr
            else f"(no output — check: fly logs --app {temporal_app_name})"
        )
        _emit(console, "error", f"Temporal namespace init failed:\n  {stderr}")
        return False
