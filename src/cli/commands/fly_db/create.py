"""Fly Postgres create commands (managed and unmanaged)."""

from typing import Annotated

import typer

from src.cli.shared.console import console, with_error_handling
from src.cli.shared.fly import check_prerequisites, get_fly_controller
from src.infra.flyio.constants import FlyConstants

from .settings import (
    _generate_default_db_name,
    _get_runtime,
    _handle_name_collision,
    _load_fly_db_settings,
    _set_production_database_url,
)

create_app = typer.Typer(
    name="create",
    help="Create Fly Postgres databases (managed or unmanaged).",
    no_args_is_help=True,
)


@create_app.command("managed")
@with_error_handling
def create_managed(
    name: Annotated[
        str | None,
        typer.Option(
            "--name", "-n", help="Cluster name (from config if not specified)"
        ),
    ] = None,
    region: Annotated[
        str | None,
        typer.Option(
            "--region", "-r", help="Fly.io region (from config if not specified)"
        ),
    ] = None,
    plan: Annotated[
        str | None,
        typer.Option(
            "--plan",
            "-p",
            help="Pricing plan: basic, development, production, production-xl",
        ),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Fly.io organization slug"),
    ] = None,
    volume_size: Annotated[
        int | None,
        typer.Option(
            "--volume-size",
            "-v",
            help="Storage size in GB (from config if not specified)",
        ),
    ] = None,
    pg_major_version: Annotated[
        int | None,
        typer.Option("--pg-version", help="PostgreSQL major version (default: 16)"),
    ] = None,
    enable_postgis: Annotated[
        bool,
        typer.Option("--postgis", help="Enable PostGIS extension support"),
    ] = False,
) -> None:
    """Create a Fly Managed Postgres (MPG) cluster.

    This creates a fully managed PostgreSQL database on Fly.io with automatic
    backups, high availability, and easy scaling. Recommended for most use cases.

    Options not provided will fall back to values from config.yaml.

    Examples:
        # Create using all config defaults
        api-forge-cli fly db create managed

        # Create with custom name
        api-forge-cli fly db create managed --name my-app-db

        # Specify region and plan
        api-forge-cli fly db create managed --name my-app-db --region lhr --plan production

        # Enable PostGIS
        api-forge-cli fly db create managed --postgis
    """
    controller = get_fly_controller()
    check_prerequisites(controller)

    # Load settings from config for defaults
    settings = _load_fly_db_settings()

    # Generate deterministic name if not provided
    if not name and not settings.name:
        settings.name = _generate_default_db_name(settings)

    effective_name = name if name else settings.name
    effective_region = region or settings.region
    effective_org = org or settings.org
    effective_plan = plan or FlyConstants.DEFAULT_MPG_PLAN
    effective_volume_size = volume_size or settings.volume_size_gb

    console.print_header("Create Fly Managed Postgres")
    console.info(f"Name: {effective_name}")
    console.info(f"Organization: {effective_org}")
    console.info(f"Region: {effective_region}")
    console.info(f"Plan: {effective_plan}")
    console.info(f"Storage: {effective_volume_size}GB")
    if enable_postgis:
        console.info("PostGIS: enabled")

    result = controller.mpg_create(
        name=effective_name,
        region=effective_region,
        plan=effective_plan,
        org=effective_org,
        volume_size=effective_volume_size,
        pg_major_version=pg_major_version,
        enable_postgis=enable_postgis,
    )

    if result.success:
        console.ok(f"Fly Managed Postgres cluster created: {effective_name}")

        # Get connection string from Fly (contains password)
        success, conn_str = controller.mpg_connection_string(effective_name)
        if success:
            from urllib.parse import urlparse

            parsed = urlparse(conn_str)
            _set_production_database_url(effective_name, conn_str, is_managed=True)

            # Also provide local development connection string (via proxy)
            local_conn_str = f"postgres://postgres@localhost:{FlyConstants.PROXY_LOCAL_PORT}/postgres"
            console.info(
                f"Local dev connection (via proxy): [dim]{local_conn_str}[/dim]"
            )

            # Verify password in secrets file matches what Fly returned
            db_settings = _get_runtime().get_settings()
            if db_settings.superuser_password and parsed.password:
                if db_settings.superuser_password == parsed.password:
                    console.ok(
                        "Verified: secrets file password matches Fly database password"
                    )
                else:
                    console.warn(
                        "Password mismatch: secrets file does not match Fly database password.\n"
                        "  Update infra/secrets/keys/postgres_password.txt with the password from Fly."
                    )
        else:
            console.warn(f"Could not retrieve connection string: {conn_str}")

        console.print("\n[bold]Next steps:[/bold]")
        console.info(
            "1. Attach to your app: api-forge-cli fly db attach --cluster "
            + effective_name
        )
        console.info(
            "2. Initialize database: api-forge-cli fly db init --cluster "
            + effective_name
        )
    else:
        console.error("Failed to create Fly Managed Postgres cluster")
        if result.stderr:
            console.print(f"[dim]{result.stderr}[/dim]")
            is_own_db = _handle_name_collision(
                controller, effective_name, effective_org, result.stderr
            )
            # If the database already exists in user's account, try to get connection string
            if is_own_db:
                success, conn_str = controller.mpg_connection_string(effective_name)
                if success:
                    _set_production_database_url(
                        effective_name, conn_str, is_managed=True
                    )
                console.print("\n[bold]Next steps:[/bold]")
                console.info(
                    "1. Attach to your app: api-forge-cli fly db attach --cluster "
                    + effective_name
                )
                console.info(
                    "2. Initialize database: api-forge-cli fly db init --cluster "
                    + effective_name
                )
                # Exit with success since the database exists
                return
        raise typer.Exit(1)


@create_app.command("unmanaged")
@with_error_handling
def create_unmanaged(
    name: Annotated[
        str | None,
        typer.Option(
            "--name", "-n", help="Cluster app name (from config if not specified)"
        ),
    ] = None,
    region: Annotated[
        str | None,
        typer.Option(
            "--region", "-r", help="Fly.io region (from config if not specified)"
        ),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option("--org", "-o", help="Fly.io organization slug"),
    ] = None,
    volume_size: Annotated[
        int | None,
        typer.Option(
            "--volume-size",
            "-v",
            help="Storage size in GB (from config if not specified)",
        ),
    ] = None,
    initial_cluster_size: Annotated[
        int | None,
        typer.Option(
            "--cluster-size",
            help="Initial number of nodes (from config if not specified)",
        ),
    ] = None,
    vm_cpus: Annotated[
        int | None,
        typer.Option("--vm-cpus", help="Number of CPUs (from config if not specified)"),
    ] = None,
    vm_cpu_kind: Annotated[
        str | None,
        typer.Option(
            "--vm-cpu-kind",
            help="CPU type: shared, performance, dedicated (from config if not specified)",
        ),
    ] = None,
    vm_memory: Annotated[
        int | None,
        typer.Option("--vm-memory", help="Memory in MB (from config if not specified)"),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option(
            "--password", help="Superuser password (auto-generated if not provided)"
        ),
    ] = None,
) -> None:
    """Create an unmanaged (legacy) Fly Postgres cluster.

    This creates a self-managed PostgreSQL cluster. You are responsible for
    backups, failover, and maintenance. For most use cases, prefer 'managed'.

    Options not provided will fall back to values from config.yaml.

    Examples:
        # Create using all config defaults
        api-forge-cli fly db create unmanaged

        # Create with custom name
        api-forge-cli fly db create unmanaged --name my-app-db

        # Specify compute resources
        api-forge-cli fly db create unmanaged --vm-cpus 2 --vm-memory 4096

        # Multi-node cluster
        api-forge-cli fly db create unmanaged --cluster-size 3
    """

    controller = get_fly_controller()
    check_prerequisites(controller)

    # Load settings from config for defaults
    settings = _load_fly_db_settings()

    # Generate deterministic name if not provided
    if not name and not settings.name:
        settings.name = _generate_default_db_name(settings)

    effective_name = name if name else settings.name
    effective_region = region or settings.region
    effective_org = org or settings.org
    effective_volume_size = volume_size or settings.volume_size_gb
    effective_cluster_size = initial_cluster_size or settings.initial_cluster_size
    effective_vm_cpus = vm_cpus or settings.vm_cpus
    effective_vm_cpu_kind = vm_cpu_kind or settings.vm_cpu_kind
    effective_vm_memory = vm_memory or settings.vm_memory_mb
    password = (
        password
        or _get_runtime().get_settings().ensure_superuser_password().superuser_password
    )

    console.print_header("Create Fly Postgres (Unmanaged)")
    if effective_name:
        console.info(f"Name: {effective_name}")
    else:
        console.info("Name: (auto-generated by Fly.io)")
    console.info(f"Organization: {effective_org}")
    console.info(f"Region: {effective_region}")
    console.info(f"Storage: {effective_volume_size}GB")
    console.info(f"Cluster size: {effective_cluster_size}")
    console.info(
        f"VM: {effective_vm_cpus} CPUs ({effective_vm_cpu_kind}), {effective_vm_memory}MB RAM"
    )
    console.warn(
        "Note: This creates self-managed Postgres. Consider 'managed' for easier operations."
    )

    result = controller.postgres_create(
        name=effective_name,
        region=effective_region,
        org=effective_org,
        volume_size=effective_volume_size,
        initial_cluster_size=effective_cluster_size,
        vm_cpus=effective_vm_cpus,
        vm_cpu_kind=effective_vm_cpu_kind,
        vm_memory=effective_vm_memory,
        password=password,
    )

    if result.success:
        console.ok(f"Fly Postgres cluster created: {effective_name}")

        _set_production_database_url(effective_name, is_managed=False)

        # Local dev connection string (via fly proxy for unmanaged)
        local_conn_str = (
            f"postgres://postgres@localhost:{FlyConstants.PROXY_LOCAL_PORT}/postgres"
        )
        console.info(f"Local dev connection (via proxy): [dim]{local_conn_str}[/dim]")

        # Confirm the password source
        console.info(
            "Database password: using value from infra/secrets/keys/postgres_password.txt"
        )

        console.print("\n[bold]Next steps:[/bold]")
        console.info(
            f"1. Attach to app: fly postgres attach {effective_name} -a <your-app>"
        )
        console.info(
            f"2. Initialize database: api-forge-cli fly db init --cluster {effective_name}"
        )
    else:
        console.error("Failed to create Fly Postgres cluster")
        if result.stderr:
            console.print(f"[dim]{result.stderr}[/dim]")
            is_own_db = _handle_name_collision(
                controller, effective_name, effective_org, result.stderr
            )
            # If the database already exists in user's account, still update .env
            if is_own_db:
                _set_production_database_url(effective_name, is_managed=False)
                console.print("\n[bold]Next steps:[/bold]")
                console.info(
                    f"1. Attach to app: fly postgres attach {effective_name} -a <your-app>"
                )
                console.info(
                    f"2. Initialize database: api-forge-cli fly db init --cluster {effective_name}"
                )
                # Exit with success since the database exists
                return
        raise typer.Exit(1)
