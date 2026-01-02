"""Shared database management utilities for both prod and k8s deployments.

This module contains common functionality used by both Docker Compose (prod)
and Kubernetes (k8s) database management commands.
"""

import typer

from src.cli.shared.console import console
from src.utils.paths import get_project_root


def parse_connection_string(conn_str: str) -> dict[str, str | None]:
    """Parse a PostgreSQL connection string into components.

    Supports formats:
    - postgres://user:pass@host:port/database?params
    - postgresql://user:pass@host:port/database?params

    Args:
        conn_str: PostgreSQL connection string

    Returns:
        Dictionary with keys: username, password, host, port, database, sslmode
    """
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(conn_str)

    result: dict[str, str | None] = {
        "username": parsed.username,
        "password": parsed.password,
        "host": parsed.hostname,
        "port": str(parsed.port) if parsed.port else None,
        "database": parsed.path.lstrip("/") if parsed.path else None,
        "sslmode": None,
    }

    # Parse query params for sslmode
    if parsed.query:
        params = parse_qs(parsed.query)
        if "sslmode" in params:
            result["sslmode"] = params["sslmode"][0]

    return result


def build_connection_string(
    *,
    username: str,
    host: str,
    port: str,
    database: str,
    sslmode: str | None = None,
    include_password: bool = False,
    password: str | None = None,
) -> str:
    """Build a PostgreSQL connection string from components.

    Args:
        username: Database username
        host: Database host
        port: Database port
        database: Database name
        sslmode: SSL mode (e.g., 'require', 'verify-full')
        include_password: Whether to include password in connection string
        password: Database password (only used if include_password=True)

    Returns:
        PostgreSQL connection string
    """
    url = f"postgres://{username}"
    if include_password and password:
        url += f":{password}"
    url += f"@{host}:{port}/{database}"
    if sslmode:
        url += f"?sslmode={sslmode}"
    return url


def update_env_file(updates: dict[str, str]) -> None:
    """Update specific keys in the .env file.

    Updates existing keys or appends new ones if not found.
    Preserves comments and formatting of other lines.

    Args:
        updates: Dictionary of key-value pairs to update

    Raises:
        typer.Exit: If .env file is not found
    """
    env_path = get_project_root() / ".env"

    if not env_path.exists():
        console.print("[red]❌ .env file not found[/red]")
        raise typer.Exit(1)

    lines = env_path.read_text().splitlines()
    updated_keys: set[str] = set()

    # Update existing keys
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0]
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # Add any keys that weren't found
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n")


def read_env_example_values(keys: list[str]) -> dict[str, str]:
    """Read specific values from .env.example file.

    Args:
        keys: List of environment variable keys to read

    Returns:
        Dictionary of key-value pairs found in .env.example

    Raises:
        typer.Exit: If .env.example file is not found
    """
    env_example_path = get_project_root() / ".env.example"

    if not env_example_path.exists():
        console.print("[red]❌ .env.example file not found[/red]")
        raise typer.Exit(1)

    values: dict[str, str] = {}
    for line in env_example_path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            if key in keys:
                values[key] = value

    return values


def save_password_to_secrets(password: str) -> None:
    """Save password to secrets file, backing up existing file if present.

    Args:
        password: Password to save

    Creates:
        - infra/secrets/keys/postgres_password.txt with mode 0600
        - infra/secrets/keys/postgres_password.txt.bak (backup if file exists)
    """
    secrets_dir = get_project_root() / "infra" / "secrets" / "keys"
    secrets_dir.mkdir(parents=True, exist_ok=True)

    password_file = secrets_dir / "postgres_password.txt"

    # Backup existing file
    if password_file.exists():
        backup_file = secrets_dir / "postgres_password.txt.bak"
        import shutil

        shutil.copy2(password_file, backup_file)
        console.print(f"[dim]Backed up existing password to {backup_file.name}[/dim]")

    password_file.write_text(password)
    # Set restrictive permissions
    password_file.chmod(0o600)


def update_bundled_postgres_config(enabled: bool) -> None:
    """Update bundled_postgres.enabled in config.yaml.

    Args:
        enabled: Whether bundled PostgreSQL is enabled

    Modifies:
        config.yaml - sets database.bundled_postgres.enabled
    """
    from src.app.runtime.config.config_loader import load_config, save_config

    config = load_config(processed=False)
    if isinstance(config, dict):
        config["config"]["database"]["bundled_postgres"]["enabled"] = enabled
        save_config(config)
    else:
        # It's a ConfigData object
        config.database.bundled_postgres.enabled = enabled
        save_config(config)


def validate_external_db_params(
    *,
    connection_string: str | None,
    host: str | None,
    port: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
    sslmode: str | None,
) -> tuple[str, str, str, str, str, str | None]:
    """Validate and merge external database connection parameters.

    Parses connection string if provided, then applies parameter overrides.
    Validates that all required parameters are present.

    Args:
        connection_string: Optional connection string to parse
        host: Optional host override
        port: Optional port override
        username: Optional username override
        password: Optional password override
        database: Optional database override
        sslmode: Optional SSL mode override

    Returns:
        Tuple of (host, port, username, password, database, sslmode)

    Raises:
        typer.Exit: If required parameters are missing
    """
    # Parse connection string if provided
    parsed: dict[str, str | None] = {}
    if connection_string:
        console.print("[cyan]ℹ[/cyan]  Parsing connection string...")
        parsed = parse_connection_string(connection_string)

    # Apply overrides (standalone params take precedence)
    final_host = host or parsed.get("host")
    final_port = port or parsed.get("port") or "5432"
    final_username = username or parsed.get("username")
    final_password = password or parsed.get("password")
    final_database = database or parsed.get("database")
    final_sslmode = sslmode or parsed.get("sslmode")

    # Validate required fields
    missing = []
    if not final_host:
        missing.append("host")
    if not final_username:
        missing.append("username")
    if not final_password:
        missing.append("password")
    if not final_database:
        missing.append("database")

    if missing:
        console.error(f"Missing required parameters: {', '.join(missing)}")
        console.print(
            "[dim]Provide via --connection-string or individual options[/dim]"
        )
        raise typer.Exit(1)

    # Type narrowing for mypy
    assert final_host and final_username and final_password and final_database

    return (
        final_host,
        final_port,
        final_username,
        final_password,
        final_database,
        final_sslmode,
    )


def configure_external_database(
    *,
    connection_string: str | None,
    host: str | None,
    port: str | None,
    username: str | None,
    password: str | None,
    database: str | None,
    sslmode: str | None,
    tls_ca: str | None,
    next_steps_cmd_prefix: str,
) -> None:
    """Configure connection to an external PostgreSQL instance.

    This is the complete workflow for setting up an external database:
    1. Parse and validate connection parameters
    2. Update .env file
    3. Save password to secrets
    4. Update config.yaml
    5. Copy TLS CA certificate if provided

    Args:
        connection_string: Optional PostgreSQL connection string
        host: Optional database host
        port: Optional database port
        username: Optional database username
        password: Optional database password
        database: Optional database name
        sslmode: Optional SSL mode
        tls_ca: Optional path to TLS CA certificate file
        next_steps_cmd_prefix: Command prefix for next steps (e.g., "prod" or "k8s")
    """
    import shutil
    from pathlib import Path

    console.print_header("Configuring External PostgreSQL")

    # Validate and merge parameters
    (
        final_host,
        final_port,
        final_username,
        final_password,
        final_database,
        final_sslmode,
    ) = validate_external_db_params(
        connection_string=connection_string,
        host=host,
        port=port,
        username=username,
        password=password,
        database=database,
        sslmode=sslmode,
    )

    # Build connection string WITHOUT password
    conn_url = build_connection_string(
        username=final_username,
        host=final_host,
        port=final_port,
        database=final_database,
        sslmode=final_sslmode,
        include_password=False,
    )

    console.print(f"[cyan]ℹ[/cyan]  Host: {final_host}:{final_port}")
    console.print(f"[cyan]ℹ[/cyan]  User: {final_username}")
    console.print(f"[cyan]ℹ[/cyan]  Database: {final_database}")
    if final_sslmode:
        console.print(f"[cyan]ℹ[/cyan]  SSL Mode: {final_sslmode}")

    # Step 1: Update .env file
    console.print("\n[cyan]ℹ[/cyan]  Updating .env file...")
    update_env_file(
        {
            "PRODUCTION_DATABASE_URL": conn_url,
            "PG_SUPERUSER": final_username,
            "PG_DB": final_database,
        }
    )
    console.ok(".env file updated")

    # Step 2: Save password to secrets file
    console.print("[cyan]ℹ[/cyan]  Saving password to secrets...")
    save_password_to_secrets(final_password)
    console.ok("Password saved to infra/secrets/keys/postgres_password.txt")

    # Step 3: Update config.yaml
    console.info("Updating config.yaml...")
    update_bundled_postgres_config(enabled=False)
    console.ok("config.yaml updated (bundled_postgres.enabled=false)")

    # Step 4: Copy TLS CA certificate if provided
    if tls_ca:
        console.print("[cyan]ℹ[/cyan]  Setting up TLS CA certificate...")
        tls_ca_path = Path(tls_ca)
        if not tls_ca_path.exists():
            console.error(f"TLS CA file not found: {tls_ca}")
            raise typer.Exit(1)

        certs_dir = get_project_root() / "infra" / "secrets" / "certs"
        certs_dir.mkdir(parents=True, exist_ok=True)

        # Copy to dedicated external postgres CA file
        external_ca_file = certs_dir / "ca-bundle-postgres-external.crt"
        shutil.copy2(tls_ca_path, external_ca_file)
        external_ca_file.chmod(0o644)
        console.ok(
            f"Copied TLS CA to {external_ca_file.relative_to(get_project_root())}"
        )

        # Append to ca-bundle.crt
        ca_bundle_file = certs_dir / "ca-bundle.crt"
        if ca_bundle_file.exists():
            # Read existing content
            existing_content = ca_bundle_file.read_text()
            external_ca_content = external_ca_file.read_text()

            # Check if external CA is already in bundle
            if external_ca_content.strip() not in existing_content:
                # Append external CA to bundle
                with ca_bundle_file.open("a") as f:
                    f.write("\n# External PostgreSQL CA Certificate\n")
                    f.write(external_ca_content)
                console.ok("Appended external CA to ca-bundle.crt")
            else:
                console.print("[dim]External CA already present in ca-bundle.crt[/dim]")
        else:
            # Create ca-bundle.crt with just the external CA
            with ca_bundle_file.open("w") as f:
                f.write("# External PostgreSQL CA Certificate\n")
                f.write(external_ca_file.read_text())
            ca_bundle_file.chmod(0o644)
            console.ok("Created ca-bundle.crt with external CA")

    console.print("\n[bold green]🎉 External PostgreSQL configured![/bold green]")
    console.print("\n[dim]Next steps:[/dim]")
    console.print(
        f"  1. Run 'uv run api-forge-cli {next_steps_cmd_prefix} db init' to initialize database"
    )
    console.print(
        f"  2. Run 'uv run api-forge-cli {next_steps_cmd_prefix} db verify' to verify setup"
    )
