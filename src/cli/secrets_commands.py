"""Secrets management CLI commands."""

import subprocess
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
        help="Regenerate ALL secrets without prompting (overwrites existing values)",
    ),
    pki: bool = typer.Option(
        False,
        "--pki",
        help="Also generate PKI certificates (root CA, intermediate CA, service certs for PostgreSQL, Redis, Temporal)",
    ),
    oidc_google_secret: str = typer.Option(
        None,
        "--oidc-google-secret",
        help="Google OIDC client secret (avoids interactive prompt)",
    ),
    oidc_microsoft_secret: str = typer.Option(
        None,
        "--oidc-microsoft-secret",
        help="Microsoft OIDC client secret (avoids interactive prompt)",
    ),
    oidc_keycloak_secret: str = typer.Option(
        None,
        "--oidc-keycloak-secret",
        help="Keycloak OIDC client secret (avoids interactive prompt)",
    ),
) -> None:
    """
    🔐 Generate all production secrets (database passwords, signing keys, etc.).

    This command runs the generate_secrets.sh script which creates:
    - PostgreSQL passwords (postgres, appuser, backupuser, temporaluser)
    - Redis password
    - Session signing secret
    - CSRF signing secret
    - OIDC client secrets (prompted interactively)
    - Optionally: TLS certificates for PostgreSQL, Redis, and Temporal (with --pki flag)

    The secrets are stored in infra/secrets/keys/.
    Certificates are stored in infra/secrets/certs/ (only with --pki flag).

    The script automatically backs up existing secrets before regenerating.

    Examples:
        # Generate secrets only (prompts for OIDC values)
        uv run api-forge-cli secrets generate

        # Generate secrets AND TLS certificates
        uv run api-forge-cli secrets generate --pki

        # Force regenerate ALL secrets (for rotation)
        uv run api-forge-cli secrets generate --force
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

    # Run generate_secrets.sh
    if pki:
        console.print("\n[cyan]🔐 Generating secrets and PKI certificates...[/cyan]\n")
    else:
        console.print("\n[cyan]🔐 Generating secrets...[/cyan]\n")

    try:
        # Make script executable
        subprocess.run(["chmod", "+x", str(generate_script)], check=True)

        # Build command arguments
        cmd = [str(generate_script)]
        if pki:
            cmd.append("--generate-pki")
        if force:
            # Pass --force to the script to regenerate all secrets
            cmd.append("--force")
        
        # Pass OIDC secrets if provided (avoids interactive prompts)
        if oidc_google_secret:
            cmd.extend(["--oidc-google-secret", oidc_google_secret])
        if oidc_microsoft_secret:
            cmd.extend(["--oidc-microsoft-secret", oidc_microsoft_secret])
        if oidc_keycloak_secret:
            cmd.extend(["--oidc-keycloak-secret", oidc_keycloak_secret])

        # Run the script interactively (no capture_output so user can see prompts)
        result = subprocess.run(
            cmd,
            cwd=project_root,
            text=True,
        )

        if result.returncode != 0:
            console.print(f"\n[red]❌ Secret generation failed with exit code {result.returncode}[/red]")
            raise typer.Exit(1)

        # Display success message
        console.print()
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

    # Check keys (matching what generate_secrets.sh actually creates)
    key_files = [
        ("Database", "postgres_password.txt"),
        ("Database", "postgres_app_user_pw.txt"),
        ("Database", "postgres_app_ro_pw.txt"),
        ("Database", "postgres_app_owner_pw.txt"),
        ("Database", "postgres_temporal_pw.txt"),
        ("Redis", "redis_password.txt"),
        ("Session", "session_signing_secret.txt"),
        ("CSRF", "csrf_signing_secret.txt"),
        ("OIDC", "oidc_google_client_secret.txt"),
        ("OIDC", "oidc_microsoft_client_secret.txt"),
        ("OIDC", "oidc_keycloak_client_secret.txt"),
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

    # Check certificates (PKI structure with subdirectories)
    cert_files = [
        ("Root CA", "root-ca.crt"),
        ("Intermediate CA", "intermediate-ca.crt"),
        ("CA Bundle", "ca-bundle.crt"),
        ("PostgreSQL Server", "postgres/server.crt"),
        ("PostgreSQL Key", "postgres/server.key"),
        ("Redis Server", "redis/server.crt"),
        ("Redis Key", "redis/server.key"),
        ("Temporal Server", "temporal/server.crt"),
        ("Temporal Key", "temporal/server.key"),
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
        "postgres_app_user_pw.txt",
        "postgres_app_ro_pw.txt",
        "postgres_app_owner_pw.txt",
        "postgres_temporal_pw.txt",
        "redis_password.txt",
        "session_signing_secret.txt",
        "csrf_signing_secret.txt",
        "oidc_google_client_secret.txt",
        "oidc_microsoft_client_secret.txt",
        "oidc_keycloak_client_secret.txt",
    ]

    required_certs = [
        "root-ca.crt",
        "intermediate-ca.crt",
        "ca-bundle.crt",
        "postgres/server.crt",
        "postgres/server.key",
        "redis/server.crt",
        "redis/server.key",
        "temporal/server.crt",
        "temporal/server.key",
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
