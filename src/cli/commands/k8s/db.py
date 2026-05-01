"""PostgreSQL database management for Kubernetes deployments.

This module provides db subcommands under 'k8s' for managing PostgreSQL
databases in Kubernetes/Helm environments.
"""

import os
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from src.cli.commands.db import DbRuntime
from src.cli.commands.db.cli_helpers import (
    execute_backup,
    execute_init,
    execute_migrate,
    execute_reset,
    execute_status,
    execute_sync,
    execute_verify,
)
from src.cli.commands.k8s.db_runtime import (
    get_k8s_runtime,
    resolve_statefulset_conflict,
)
from src.cli.context import get_cli_context
from src.cli.deployment.helm_deployer import ConfigSynchronizer
from src.cli.deployment.status_display import is_temporal_enabled
from src.cli.shared.console import console, with_error_handling
from src.cli.shared.db_utils import (
    configure_external_database,
    read_env_example_values,
    update_bundled_postgres_config,
    update_env_vars,
)
from src.infra.constants import DeploymentConstants, DeploymentPaths
from src.infra.k8s import get_namespace, get_postgres_label
from src.infra.k8s.controller import KubernetesControllerSync
from src.utils.paths import get_project_root

# ---------------------------------------------------------------------------
# Typer App
# ---------------------------------------------------------------------------

k8s_db_app = typer.Typer(
    name="db",
    help="PostgreSQL database management for Kubernetes.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _get_components() -> tuple[
    DeploymentConstants, DeploymentPaths, KubernetesControllerSync
]:
    """Return deployment constants, paths, and controller from CLI context."""
    ctx = get_cli_context()
    return ctx.constants, ctx.paths, ctx.k8s_controller


def _get_namespace_and_label() -> tuple[str, str]:
    """Resolve namespace and postgres label at call time."""
    return get_namespace(), get_postgres_label()


def _get_runtime() -> DbRuntime:
    """Return the Kubernetes DB runtime."""
    return get_k8s_runtime()


@k8s_db_app.command()
@with_error_handling
def create(
    # Mode selection (mutually exclusive)
    bundled: Annotated[
        bool,
        typer.Option(
            "--bundled",
            help="Deploy bundled PostgreSQL to Kubernetes",
        ),
    ] = False,
    external: Annotated[
        bool,
        typer.Option(
            "--external",
            help="Configure connection to external PostgreSQL",
        ),
    ] = False,
    # External mode parameters
    connection_string: Annotated[
        str | None,
        typer.Option(
            "--connection-string",
            "-c",
            help="Full PostgreSQL connection string (postgres://user:pass@host:port/db)",
        ),
    ] = None,
    host: Annotated[
        str | None,
        typer.Option(
            "--host",
            "-H",
            help="Database host (overrides connection string)",
        ),
    ] = None,
    port: Annotated[
        str | None,
        typer.Option(
            "--port",
            "-P",
            help="Database port (overrides connection string)",
        ),
    ] = None,
    username: Annotated[
        str | None,
        typer.Option(
            "--username",
            "-u",
            help="Database username (overrides connection string)",
        ),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option(
            "--password",
            "-p",
            help="Database password (overrides connection string)",
        ),
    ] = None,
    database: Annotated[
        str | None,
        typer.Option(
            "--database",
            "-d",
            help="Database name (overrides connection string)",
        ),
    ] = None,
    sslmode: Annotated[
        str | None,
        typer.Option(
            "--sslmode",
            help="SSL mode (e.g., require, verify-full)",
        ),
    ] = None,
    tls_ca: Annotated[
        str | None,
        typer.Option(
            "--tls-ca",
            help="Path to TLS CA certificate file for external PostgreSQL (e.g., Aiven CA)",
        ),
    ] = None,
    # Bundled mode parameters
    values_file: Annotated[
        Path | None,
        typer.Option(
            "--values",
            "-f",
            help="Custom Helm values file (bundled mode only)",
        ),
    ] = None,
    wait: Annotated[
        bool,
        typer.Option(
            "--wait/--no-wait",
            help="Wait for PostgreSQL to be ready (bundled mode only)",
        ),
    ] = True,
) -> None:
    """Configure PostgreSQL database for Kubernetes deployment.

    Two modes are available:

    --bundled: Deploy a bundled PostgreSQL instance to Kubernetes using Helm.
    This deploys secrets, the PostgreSQL chart, and configures security settings.

    --external: Configure connection to an external PostgreSQL instance (e.g., Aiven, RDS).
    This updates .env and config.yaml with connection details.

    Examples:
        # Deploy bundled PostgreSQL
        uv run api-forge-cli k8s db create --bundled
        uv run api-forge-cli k8s db create --bundled --values custom-values.yaml

        # Configure external PostgreSQL with connection string
        uv run api-forge-cli k8s db create --external \\
            --connection-string "postgres://admin:secret@db.example.com:5432/mydb?sslmode=require"

        # Configure external PostgreSQL with individual parameters
        uv run api-forge-cli k8s db create --external \\
            --host db.example.com --port 5432 \\
            --username admin --password secret --database mydb

        # Mix: connection string with override
        uv run api-forge-cli k8s db create --external \\
            --connection-string "postgres://user:pass@host:5432/db" \\
            --password new-secret  # Override password from connection string
    """
    # Validate mode selection
    if bundled and external:
        console.print("[red]❌ Cannot use both --bundled and --external[/red]")
        raise typer.Exit(1)

    if not bundled and not external:
        console.print("[red]❌ Must specify either --bundled or --external[/red]")
        console.print("[dim]Use --bundled to deploy PostgreSQL to Kubernetes[/dim]")
        console.print("[dim]Use --external to configure an external database[/dim]")
        raise typer.Exit(1)

    if external:
        configure_external_database(
            connection_string=connection_string,
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            sslmode=sslmode,
            tls_ca=tls_ca,
            next_steps_cmd_prefix="k8s",
        )
    else:
        _create_bundled(values_file=values_file, wait=wait)


def _create_bundled(*, values_file: Path | None, wait: bool) -> None:
    """Deploy bundled PostgreSQL to Kubernetes using Helm."""
    from rich.progress import Progress

    from src.cli.deployment.helm_deployer.secret_manager import (
        HelmDeploymentSecretManager,
    )
    from src.cli.deployment.shell_commands import ShellCommands

    constants, paths, controller = _get_components()
    namespace, postgres_label = _get_namespace_and_label()

    console.print_header("Deploying Bundled PostgreSQL to Kubernetes")

    # Read bundled defaults from .env.example
    bundled_keys = ["PRODUCTION_DATABASE_URL", "PG_SUPERUSER", "PG_DB"]
    bundled_defaults = read_env_example_values(bundled_keys)

    if not bundled_defaults:
        console.print("[red]❌ Could not read bundled defaults from .env.example[/red]")
        raise typer.Exit(1)

    # Update .env with bundled defaults from .env.example
    console.info("Updating .env file for bundled PostgreSQL...")
    update_env_vars(bundled_defaults)
    console.ok(".env file updated")

    # Update config.yaml
    console.info("Updating config.yaml...")
    update_bundled_postgres_config(enabled=True)
    console.ok("config.yaml updated (bundled_postgres.enabled=true)")
    project_root = get_project_root()

    # Step 1: Deploy secrets required by PostgreSQL
    console.info("Deploying secrets...")
    commands = ShellCommands(project_root)
    secret_manager = HelmDeploymentSecretManager(
        commands=commands,
        console=console,
        paths=paths,
    )
    secret_manager.deploy_secrets(
        namespace=namespace,
        progress_factory=Progress,
    )
    console.ok("Secrets deployed")

    # Step 1.5: Copy config files
    console.info("Copying config files to Helm staging area...")
    sync = ConfigSynchronizer(
        console=console,
        paths=paths,
    )
    sync.copy_config_files(progress_factory=Progress)
    console.ok("Config files copied")

    # Step 1.6: Build and load PostgreSQL image
    console.info("Building PostgreSQL image...")
    from src.cli.deployment.helm_deployer.image_builder import ImageBuilder

    image_builder = ImageBuilder(
        console=console,
        commands=commands,
        controller=controller,
        paths=paths,
        constants=constants,
    )

    # Build images and load into cluster (Minikube/Kind)
    image_tag = image_builder.build_and_tag_images(
        progress_factory=Progress,
        registry=None,  # Local cluster, no registry needed
    )
    console.ok(f"PostgreSQL image built and loaded: {image_tag}")

    # Step 2: Deploy PostgreSQL
    # Try standalone bundled chart first, fallback to Bitnami
    standalone_chart_path = paths.postgres_standalone_chart

    if (
        standalone_chart_path.exists()
        and (standalone_chart_path / "Chart.yaml").exists()
    ):
        chart = str(standalone_chart_path)
        console.info(f"Using bundled PostgreSQL chart: {standalone_chart_path.name}")
        if not values_file:
            # Use the standalone chart's values.yaml
            standalone_values = standalone_chart_path / "values.yaml"
            if standalone_values.exists():
                values_file = standalone_values
                console.info(f"Using chart values: {standalone_values.name}")
    else:
        # Fallback to Bitnami chart
        chart = "oci://registry-1.docker.io/bitnamicharts/postgresql"
        console.warn("Bundled chart not found, using Bitnami PostgreSQL chart")
        console.print(
            "[dim]Note: Bitnami is deprecating free charts. "
            "Consider using bundled chart or managed database.[/dim]"
        )
        if not values_file:
            values_file = paths.bitnami_postgres_values_yaml

    if values_file and values_file.exists():
        console.info(f"Using values file: {values_file}")
    else:
        console.info("No values file provided or found, using defaults")
        values_file = None

    # Pre-flight check: Check if StatefulSet exists and might have conflicts
    # This prevents Helm from hanging on --wait when immutable fields changed
    if controller.resource_exists(
        "statefulset", constants.POSTGRES_RESOURCE_NAME, namespace
    ):
        import sys

        # In CI environments (non-interactive), auto-recreate to avoid hanging
        is_ci = not sys.stdin.isatty() or os.environ.get("CI") == "true"

        if is_ci:
            console.warn(
                f"StatefulSet '{constants.POSTGRES_RESOURCE_NAME}' already exists "
                "(CI mode: auto-recreating)"
            )
            action = "recreate"
        else:
            console.warn(
                f"StatefulSet '{constants.POSTGRES_RESOURCE_NAME}' already exists"
            )
            console.print(
                "[yellow]⚠[/yellow]  This may cause conflicts if template changed immutable fields"
            )
            action = console.prompt_resource_conflict(
                resource_type="StatefulSet",
                resource_name=constants.POSTGRES_RESOURCE_NAME,
                namespace=namespace,
                data_warning=True,
            )

        if action == "abort":
            console.error("Deployment aborted by user")
            raise typer.Exit(1)

        if action == "recreate":
            if not resolve_statefulset_conflict(
                controller,
                constants.POSTGRES_RESOURCE_NAME,
                namespace,
                constants.POSTGRES_POD_LABEL,
            ):
                raise typer.Exit(1)

    # Build helm command
    helm_args = [
        "helm",
        "upgrade",
        "--install",
        "postgresql",
        chart,
        "-n",
        namespace,
        "--create-namespace",
        "--timeout",
        "10m",
    ]

    if values_file:
        helm_args.extend(["-f", str(values_file)])

    # Set the image tag to match what was built/loaded
    # The image_builder uses content-based tags (hash-xxx or git-xxx)
    # We must tell Helm to use this tag instead of :latest
    helm_args.extend(["--set", f"postgres.image.tag={image_tag}"])

    if wait:
        helm_args.append("--wait")

    console.print("[cyan]ℹ[/cyan]  Installing PostgreSQL...")
    console.print(f"[dim]Running: {' '.join(helm_args)}[/dim]")

    # Stream output so we can see what Helm is doing (especially useful in CI)
    process = subprocess.Popen(
        helm_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    stdout_lines = []
    if process.stdout:
        for line in process.stdout:
            stdout_lines.append(line)
            console.print(f"[dim]{line.rstrip()}[/dim]")

    returncode = process.wait()
    result = subprocess.CompletedProcess(
        args=helm_args,
        returncode=returncode,
        stdout="".join(stdout_lines),
        stderr="",
    )

    if result.returncode != 0:
        # Check if this is a StatefulSet immutable field error
        if "spec: Forbidden: updates to statefulset spec" in result.stderr:
            # Check if StatefulSet exists using controller
            if controller.resource_exists(
                "statefulset", constants.POSTGRES_RESOURCE_NAME, namespace
            ):
                # StatefulSet exists - use the prompt helper
                action = console.prompt_resource_conflict(
                    resource_type="StatefulSet",
                    resource_name=constants.POSTGRES_RESOURCE_NAME,
                    namespace=namespace,
                    data_warning=True,
                )

                if action == "recreate":
                    if not resolve_statefulset_conflict(
                        controller,
                        constants.POSTGRES_RESOURCE_NAME,
                        namespace,
                        constants.POSTGRES_POD_LABEL,
                    ):
                        raise typer.Exit(1)

                    # Fresh Helm install (upgrade --install will install since
                    # release metadata is gone)
                    console.info("Installing PostgreSQL...")
                    retry_result = subprocess.run(
                        helm_args, capture_output=True, text=True
                    )

                    if retry_result.returncode != 0:
                        console.error(
                            f"Failed to install PostgreSQL:\n{retry_result.stderr}"
                        )
                        raise typer.Exit(1)

                    console.ok("PostgreSQL deployed to Kubernetes")
                elif action == "skip":
                    console.warn(
                        "Skipping PostgreSQL deployment - keeping existing StatefulSet"
                    )
                    console.print("\n[dim]To manually update, run:[/dim]")
                    console.print(
                        f"[dim]  kubectl delete statefulset {constants.POSTGRES_RESOURCE_NAME} -n {namespace} --cascade=orphan[/dim]"
                    )
                    console.print(
                        "[dim]  uv run api-forge-cli k8s db create --bundled[/dim]"
                    )
                    return
                else:  # cancel
                    console.print("[dim]Operation cancelled.[/dim]")
                    raise typer.Exit(0)
            else:
                # StatefulSet doesn't exist but we got the error - unexpected
                console.error(f"Unexpected error:\n{result.stderr}")
                raise typer.Exit(1)
        else:
            # Different error
            console.error(f"Failed to install PostgreSQL:\n{result.stderr}")
            raise typer.Exit(1)

    console.ok("PostgreSQL deployed to Kubernetes")
    console.print(f"\n[dim]Namespace: {namespace}[/dim]")

    # Auto-initialize database after successful deployment
    console.info("\nInitializing database...")

    try:
        execute_init(_get_runtime(), label="Kubernetes")
    except typer.Exit:
        console.print("\n[dim]You can retry with:[/dim]")
        console.print("  uv run api-forge-cli k8s db init")
        raise
    except Exception as exc:
        console.error(f"Database initialization failed: {exc}")
        console.print("\n[dim]You can retry with:[/dim]")
        console.print("  uv run api-forge-cli k8s db init")
        raise typer.Exit(1) from exc

    console.ok("Database initialized successfully")
    console.print("\n[dim]Next steps:[/dim]")
    console.print("  - Run 'uv run api-forge-cli k8s db verify' to verify setup")


_K8S_LABEL = "Kubernetes"


@k8s_db_app.command(name="init")
@with_error_handling
def init_db() -> None:
    """Initialize the PostgreSQL database with roles and schema.

    Creates owner / app / read-only roles, the application database, and
    sets up the schema with proper privileges. Optionally initializes
    Temporal databases.

    Examples:
        uv run api-forge-cli k8s db init
    """
    execute_init(_get_runtime(), label=_K8S_LABEL)


@k8s_db_app.command()
@with_error_handling
def verify() -> None:
    """Verify PostgreSQL database setup and configuration.

    Checks pod readiness, role existence/attributes, database and schema
    ownership, table and sequence privileges.

    Examples:
        uv run api-forge-cli k8s db verify
    """
    execute_verify(
        _get_runtime(),
        label=_K8S_LABEL,
        superuser_mode=True,
        retry_hint=(
            'Please run "uv run api-forge-cli k8s db init" to re-initialize '
            "the database."
        ),
    )


@k8s_db_app.command()
@with_error_handling
def sync() -> None:
    """Synchronize PostgreSQL role passwords.

    Restarts PostgreSQL to pick up new secrets, then updates database role
    passwords. Use after rotating secrets.

    Examples:
        uv run api-forge-cli k8s db sync
    """
    execute_sync(_get_runtime(), label=_K8S_LABEL)


@k8s_db_app.command()
@with_error_handling
def backup(
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            help="Local directory for backup files",
        ),
    ] = None,
) -> None:
    """Create a PostgreSQL database backup from Kubernetes.

    Runs pg_dump in the pod and copies the result locally.

    Examples:
        uv run api-forge-cli k8s db backup
        uv run api-forge-cli k8s db backup --output-dir ./backups
    """
    execute_backup(
        _get_runtime(),
        label=_K8S_LABEL,
        output_dir=output_dir,
        superuser_mode=True,
    )


@k8s_db_app.command()
@with_error_handling
def reset(
    include_temporal: Annotated[
        bool,
        typer.Option(
            "--temporal/--no-temporal",
            help="Also drop Temporal databases and roles",
        ),
    ] = True,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip confirmation prompt",
        ),
    ] = False,
) -> None:
    """Reset the PostgreSQL database to clean state (DESTRUCTIVE).

    This command drops all application-created databases, roles, and schemas,
    returning PostgreSQL to a clean state ready for re-initialization.

    Drops:
    - Application database (appdb)
    - Application roles (appuser, appowner, backupuser)
    - Temporal databases and roles (if --temporal, default)

    Does NOT affect:
    - Kubernetes pods or services (use 'k8s down' to clean up)
    - PersistentVolumeClaims (use 'k8s down --pvc' to remove)
    - System databases (postgres, template0, template1)

    WARNING: This will permanently delete all database data!

    Examples:
        uv run api-forge-cli k8s db reset
        uv run api-forge-cli k8s db reset --no-temporal  # Keep Temporal data
        uv run api-forge-cli k8s db reset -y             # Skip confirmation
    """
    include_temporal = is_temporal_enabled() and include_temporal

    if not yes:
        if not console.confirm_action(
            "Reset PostgreSQL database",
            "This will permanently delete all database data including:\n"
            "  • All application databases\n"
            "  • All application roles\n"
            "  • All tables and data\n"
            + ("  • Temporal databases and roles\n" if include_temporal else ""),
        ):
            console.print("[dim]Operation cancelled[/dim]")
            raise typer.Exit(0)

    execute_reset(
        _get_runtime(),
        label=_K8S_LABEL,
        include_temporal=include_temporal,
        superuser_mode=True,
        retry_command="uv run api-forge-cli k8s db init",
    )


@k8s_db_app.command()
@with_error_handling
def status() -> None:
    """Show PostgreSQL health and performance metrics.

    Displays connection latency, active connections, database sizes, row
    counts, cache hit ratios, and uptime. Works with both bundled
    Kubernetes PostgreSQL and external databases.

    Examples:
        uv run api-forge-cli k8s db status
    """
    execute_status(_get_runtime(), label=_K8S_LABEL, superuser_mode=True)


@k8s_db_app.command()
@with_error_handling
def migrate(
    action: Annotated[
        str,
        typer.Argument(
            help=(
                "Migration action: upgrade, downgrade, current, history, revision, "
                "heads, merge, show, stamp"
            )
        ),
    ],
    revision: Annotated[
        str | None,
        typer.Argument(
            help="Target revision (for downgrade) or message (for revision)"
        ),
    ] = None,
    message: Annotated[
        str | None,
        typer.Option(
            "--message",
            "-m",
            help=(
                "Optional message (used by merge). If omitted, merge will use the second "
                "argument as the message when provided, otherwise a default."
            ),
        ),
    ] = None,
    merge_revisions: Annotated[
        list[str] | None,
        typer.Option(
            "--merge-revision",
            "-r",
            help=(
                "Revision(s) to merge (for merge). Can be provided multiple times. "
                "If omitted, merges all current heads."
            ),
        ),
    ] = None,
    purge: Annotated[
        bool,
        typer.Option(
            "--purge",
            help=(
                "For stamp only: purge the version table before stamping. "
                "Use with extreme care."
            ),
        ),
    ] = False,
    autogenerate: Annotated[
        bool,
        typer.Option(
            "--autogenerate/--no-autogenerate",
            help="Autogenerate migration from model changes (for revision)",
        ),
    ] = True,
    sql: Annotated[
        bool,
        typer.Option(
            "--sql",
            help="Generate SQL output instead of running migration",
        ),
    ] = False,
) -> None:
    """Manage database schema migrations with Alembic.

    Actions:
        upgrade [revision]  - Apply migrations up to revision (default: head)
        downgrade <revision> - Rollback to a specific revision
        current            - Show current migration revision
        history            - Show migration history
        revision <message> - Create a new migration (with --autogenerate)
        heads              - Show current head revision(s)
        merge              - Create a merge migration (default: merge all heads)
        show <revision>    - Show a specific migration's details
        stamp <revision>   - Set DB revision without running migrations

    Examples:
        # Apply all pending migrations
        uv run api-forge-cli k8s db migrate upgrade

        # Apply migrations up to a specific revision
        uv run api-forge-cli k8s db migrate upgrade abc123

        # Rollback to a specific revision
        uv run api-forge-cli k8s db migrate downgrade abc123

        # Rollback one migration
        uv run api-forge-cli k8s db migrate downgrade -1

        # Show current migration state
        uv run api-forge-cli k8s db migrate current

        # Show migration history
        uv run api-forge-cli k8s db migrate history

        # Create a new migration with autogeneration
        uv run api-forge-cli k8s db migrate revision "add user table"

        # Create empty migration template
        uv run api-forge-cli k8s db migrate revision "custom migration" --no-autogenerate

        # Generate SQL for upgrade without running it
        uv run api-forge-cli k8s db migrate upgrade --sql

        # Show current heads (useful when multiple heads exist)
        uv run api-forge-cli k8s db migrate heads

        # Merge all current heads
        uv run api-forge-cli k8s db migrate merge --message "merge heads"

        # Merge specific revisions
        uv run api-forge-cli k8s db migrate merge --message "merge" \
            -r abc123 -r def456

        # Show a specific revision
        uv run api-forge-cli k8s db migrate show 19becf30b774

        # Stamp the DB to a revision (no migration execution)
        uv run api-forge-cli k8s db migrate stamp head
    """
    execute_migrate(
        _get_runtime(),
        action=action,
        revision=revision,
        message=message,
        merge_revisions=merge_revisions or [],
        purge=purge,
        autogenerate=autogenerate,
        sql=sql,
    )


if __name__ == "__main__":
    verify()  # For quick testing
