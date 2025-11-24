"""Secrets management CLI commands."""

import subprocess
from datetime import datetime
from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from .utils import console, get_project_root

# Create the secrets command group
secrets_app = typer.Typer(help="🔐 Secrets management commands")


@secrets_app.command()
def generate(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing secrets without prompting",
    ),
    backup: bool = typer.Option(
        True,
        "--backup/--no-backup",
        help="Create backup of existing secrets before generating new ones",
    ),
) -> None:
    """
    🔐 Generate all production secrets (database passwords, signing keys, etc.).

    This command runs the generate_secrets.sh script which creates:
    - PostgreSQL passwords (postgres, appuser, backupuser, temporaluser)
    - Redis password
    - Session signing secret
    - CSRF signing secret
    - TLS certificates for PostgreSQL and Redis

    The secrets are stored in infra/secrets/keys/ and infra/secrets/certs/.

    Examples:
        # Generate secrets (prompts before overwriting)
        uv run api-forge-cli secrets generate

        # Force overwrite without prompting
        uv run api-forge-cli secrets generate --force

        # Generate without backing up existing secrets
        uv run api-forge-cli secrets generate --no-backup
    """
    project_root = Path(get_project_root())
    secrets_dir = project_root / "infra" / "secrets"
    keys_dir = secrets_dir / "keys"
    certs_dir = secrets_dir / "certs"
    generate_script = secrets_dir / "generate_secrets.sh"

    # Check if script exists
    if not generate_script.exists():
        console.print(
            "[red]❌ Error: generate_secrets.sh not found at:[/red]",
            f"   {generate_script}",
        )
        raise typer.Exit(1)

    # Check if secrets already exist
    existing_secrets = False
    if keys_dir.exists() and any(keys_dir.iterdir()):
        existing_secrets = True

    if existing_secrets and not force:
        console.print(
            Panel(
                "⚠️  [yellow]Existing secrets detected![/yellow]\n\n"
                "Regenerating secrets will:\n"
                "• Create new passwords and signing keys\n"
                "• Require redeployment of all services\n"
                "• Break existing sessions and database connections\n\n"
                "A backup will be created automatically (unless --no-backup is used).",
                title="Warning",
                border_style="yellow",
            )
        )

        confirm = typer.confirm("Do you want to continue?")
        if not confirm:
            console.print("[yellow]Operation cancelled.[/yellow]")
            raise typer.Exit(0)

    # Backup existing secrets if requested
    if backup and existing_secrets:
        console.print("\n[cyan]📦 Creating backup of existing secrets...[/cyan]")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = secrets_dir / f"backup_{timestamp}"

        try:
            backup_dir.mkdir(parents=True, exist_ok=True)

            # Backup keys
            if keys_dir.exists():
                subprocess.run(
                    ["cp", "-r", str(keys_dir), str(backup_dir / "keys")],
                    check=True,
                    capture_output=True,
                )

            # Backup certs
            if certs_dir.exists():
                subprocess.run(
                    ["cp", "-r", str(certs_dir), str(backup_dir / "certs")],
                    check=True,
                    capture_output=True,
                )

            console.print(f"[green]✅ Backup created at:[/green] {backup_dir}")

        except subprocess.CalledProcessError as e:
            console.print(f"[red]❌ Backup failed: {e.stderr.decode()}[/red]")
            raise typer.Exit(1) from e

    # Run generate_secrets.sh
    console.print("\n[cyan]🔐 Generating secrets...[/cyan]")

    try:
        # Make script executable
        subprocess.run(["chmod", "+x", str(generate_script)], check=True)

        # Run the script
        result = subprocess.run(
            [str(generate_script)],
            cwd=project_root,
            capture_output=True,
            text=True,
        )

        # Show output
        if result.stdout:
            console.print(result.stdout)

        if result.returncode != 0:
            console.print(f"[red]❌ Secret generation failed:[/red]\n{result.stderr}")
            raise typer.Exit(1)

        # Display success message
        console.print(
            Panel(
                "[green]✅ Secrets generated successfully![/green]\n\n"
                "Generated files:\n"
                f"• Keys: {keys_dir}\n"
                f"• Certificates: {certs_dir}\n\n"
                "[yellow]⚠️  Important:[/yellow]\n"
                "• These secrets are for production use\n"
                "• Keep them secure and never commit to git\n"
                "• You may need to redeploy services to use new secrets",
                title="Success",
                border_style="green",
            )
        )

    except subprocess.CalledProcessError as e:
        console.print(f"[red]❌ Error running generate_secrets.sh: {e}[/red]")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"[red]❌ Unexpected error: {e}[/red]")
        raise typer.Exit(1) from e


@secrets_app.command()
def list(
    show_values: bool = typer.Option(
        False,
        "--show-values",
        help="Show actual secret values (use with caution!)",
    ),
) -> None:
    """
    📋 List all generated secrets and their status.

    Shows which secrets have been generated and their file locations.
    Use --show-values to display actual values (NOT recommended in shared environments).

    Examples:
        # List all secrets
        uv run api-forge-cli secrets list

        # Show secret values (be careful!)
        uv run api-forge-cli secrets list --show-values
    """
    project_root = Path(get_project_root())
    secrets_dir = project_root / "infra" / "secrets"
    keys_dir = secrets_dir / "keys"
    certs_dir = secrets_dir / "certs"

    # Create table
    table = Table(title="🔐 Secrets Status")
    table.add_column("Type", style="cyan")
    table.add_column("File", style="white")
    table.add_column("Status", style="green")
    if show_values:
        table.add_column("Value", style="yellow")

    # Check keys
    key_files = [
        ("Database", "postgres_password.txt"),
        ("Database", "appuser_password.txt"),
        ("Database", "backupuser_password.txt"),
        ("Database", "temporaluser_password.txt"),
        ("Redis", "redis_password.txt"),
        ("Session", "session_signing_secret.txt"),
        ("CSRF", "csrf_signing_secret.txt"),
    ]

    for key_type, filename in key_files:
        file_path = keys_dir / filename
        if file_path.exists():
            status = "✅ Generated"
            value = ""
            if show_values:
                try:
                    value = file_path.read_text().strip()
                    # Truncate long values
                    if len(value) > 40:
                        value = value[:40] + "..."
                except Exception:
                    value = "[red]Error reading[/red]"
        else:
            status = "❌ Missing"
            value = ""

        if show_values:
            table.add_row(key_type, filename, status, value)
        else:
            table.add_row(key_type, filename, status)

    # Check certificates
    cert_files = [
        ("PostgreSQL CA", "postgres-ca.crt"),
        ("PostgreSQL Server", "postgres-server.crt"),
        ("PostgreSQL Client", "postgres-client.crt"),
        ("Redis CA", "redis-ca.crt"),
        ("Redis Server", "redis-server.crt"),
        ("Redis Client", "redis-client.crt"),
    ]

    for cert_type, filename in cert_files:
        file_path = certs_dir / filename
        if file_path.exists():
            status = "✅ Generated"
        else:
            status = "❌ Missing"

        if show_values:
            table.add_row(cert_type, filename, status, "[dim]Certificate file[/dim]")
        else:
            table.add_row(cert_type, filename, status)

    console.print(table)

    # Show summary
    keys_exist = keys_dir.exists() and any(keys_dir.iterdir())
    certs_exist = certs_dir.exists() and any(certs_dir.iterdir())

    if keys_exist and certs_exist:
        console.print("\n[green]✅ All secrets appear to be generated.[/green]")
    elif not keys_exist and not certs_exist:
        console.print(
            "\n[yellow]⚠️  No secrets found. Run:[/yellow]",
            "   uv run api-forge-cli secrets generate",
        )
    else:
        console.print(
            "\n[yellow]⚠️  Some secrets are missing. Run:[/yellow]",
            "   uv run api-forge-cli secrets generate",
        )


@secrets_app.command()
def verify(
) -> None:
    """
    ✅ Verify that all required secrets exist and are readable.

    Checks that all necessary secrets files are present and accessible.
    Does NOT validate the content or format of secrets.

    Examples:
        # Verify all secrets
        uv run api-forge-cli secrets verify
    """
    project_root = Path(get_project_root())
    secrets_dir = project_root / "infra" / "secrets"
    keys_dir = secrets_dir / "keys"
    certs_dir = secrets_dir / "certs"

    required_keys = [
        "postgres_password.txt",
        "appuser_password.txt",
        "backupuser_password.txt",
        "temporaluser_password.txt",
        "redis_password.txt",
        "session_signing_secret.txt",
        "csrf_signing_secret.txt",
    ]

    required_certs = [
        "postgres-ca.crt",
        "postgres-server.crt",
        "postgres-server.key",
        "postgres-client.crt",
        "postgres-client.key",
        "redis-ca.crt",
        "redis-server.crt",
        "redis-server.key",
        "redis-client.crt",
        "redis-client.key",
    ]

    missing_keys = []
    missing_certs = []
    unreadable = []

    # Check keys
    for filename in required_keys:
        file_path = keys_dir / filename
        if not file_path.exists():
            missing_keys.append(filename)
        else:
            try:
                content = file_path.read_text()
                if not content.strip():
                    unreadable.append(filename)
            except Exception:
                unreadable.append(filename)

    # Check certs
    for filename in required_certs:
        file_path = certs_dir / filename
        if not file_path.exists():
            missing_certs.append(filename)
        else:
            try:
                file_path.read_bytes()
            except Exception:
                unreadable.append(filename)

    # Report results
    if not missing_keys and not missing_certs and not unreadable:
        console.print(
            Panel(
                "[green]✅ All required secrets are present and readable![/green]\n\n"
                f"Keys: {len(required_keys)} files\n"
                f"Certificates: {len(required_certs)} files\n\n"
                "Your secrets are ready for production deployment.",
                title="Verification Passed",
                border_style="green",
            )
        )
        return

    # Show errors
    has_errors = False

    if missing_keys:
        has_errors = True
        console.print("\n[red]❌ Missing key files:[/red]")
        for filename in missing_keys:
            console.print(f"   • {filename}")

    if missing_certs:
        has_errors = True
        console.print("\n[red]❌ Missing certificate files:[/red]")
        for filename in missing_certs:
            console.print(f"   • {filename}")

    if unreadable:
        has_errors = True
        console.print("\n[red]❌ Unreadable files:[/red]")
        for filename in unreadable:
            console.print(f"   • {filename}")

    if has_errors:
        console.print(
            "\n[yellow]💡 To generate missing secrets, run:[/yellow]",
            "   uv run api-forge-cli secrets generate",
        )
        raise typer.Exit(1)
