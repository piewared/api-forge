"""Secrets management CLI commands."""

from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from src.cli.prompts import ConsolePromptProvider
from src.cli.shared.console import console
from src.infra.secrets import (
    GeneratorConfig,
    PKICertificateGenerator,
    SecretGenerationOrchestrator,
    SecretGenerator,
    SecretKind,
)
from src.infra.secrets.file_manager import FileSecretsManager
from src.utils.paths import get_project_root

# Create the secrets command group
secrets_app = typer.Typer(help="🔐 Secrets management commands")


def _get_file_secrets_manager(secrets_dir: Path) -> FileSecretsManager:
    """Create a FileSecretsManager for the given secrets directory."""
    return FileSecretsManager(
        secrets_dir=secrets_dir / "keys",
        certs_dir=secrets_dir / "certs",
        backups_dir=secrets_dir / "backups",
    )


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
    force_ca: bool = typer.Option(
        False,
        "--force-ca",
        help="Force regeneration of CA certificates (use with caution)",
    ),
    user_secrets_file: Path = typer.Option(
        None,
        "--user-secrets-file",
        help="Path to user-provided.env containing deterministic secrets",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Disable prompts; require secrets via CLI or file",
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
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompt for --force"
    ),
) -> None:
    """
    🔐 Generate all production secrets (database passwords, signing keys, etc.).

    This command generates:
    - PostgreSQL passwords (postgres, appuser, temporaluser)
    - Redis password
    - Session signing secret
    - CSRF signing secret
    - OIDC client secrets (prompted interactively or provided via CLI)
    - Optionally: TLS certificates for PostgreSQL, Redis, and Temporal (with --pki flag)

    The secrets are stored in infra/secrets/keys/.
    Certificates are stored in infra/secrets/certs/ (only with --pki flag).

    Existing secrets are automatically backed up before regenerating.

    Examples:
        # Generate secrets only (prompts for OIDC values)
        uv run api-forge-cli secrets generate

        # Generate secrets AND TLS certificates
        uv run api-forge-cli secrets generate --pki

        # Force regenerate ALL secrets (for rotation)
        uv run api-forge-cli secrets generate --force

        # Non-interactive mode with provided OIDC secrets
        uv run api-forge-cli secrets generate --non-interactive \\
            --oidc-google-secret "..." \\
            --oidc-microsoft-secret "..." \\
            --oidc-keycloak-secret "..."
    """
    project_root = Path(get_project_root())
    secrets_dir = project_root / "infra" / "secrets"

    # Confirm if using --force (destructive overwrite)
    if force:
        details = (
            "This will regenerate ALL secrets including:\n"
            "  • Database passwords (PostgreSQL)\n"
            "  • Redis password\n"
            "  • Session signing secret\n"
            "  • CSRF signing secret"
        )
        if pki:
            details += (
                "\n  • TLS certificates (Root CA, Intermediate CA, service certs)"
            )

        if not console.confirm_action(
            action="Regenerate ALL secrets",
            details=details,
            extra_warning="⚠️  Existing secrets will be permanently overwritten!",
            force=yes,
        ):
            console.print("[dim]Operation cancelled.[/dim]")
            raise typer.Exit(0)

    # Check dependencies
    try:
        SecretGenerator.check_dependencies()
    except RuntimeError as e:
        console.error(str(e))
        raise typer.Exit(1) from e

    # Get the secrets manager
    secrets_manager = _get_file_secrets_manager(secrets_dir)

    # Create configuration
    config = GeneratorConfig(
        secrets_manager=secrets_manager,
        secrets_dir=secrets_dir,
        non_interactive=non_interactive,
        overwrite_secrets=force,
        user_secrets_file=user_secrets_file,
        prompt_provider=ConsolePromptProvider(console.console)
        if not non_interactive
        else None,
        oidc_google_secret=oidc_google_secret,
        oidc_microsoft_secret=oidc_microsoft_secret,
        oidc_keycloak_secret=oidc_keycloak_secret,
    )

    try:
        # Backup existing secrets before force regeneration
        if force:
            backup_info = secrets_manager.backup_all()
            console.print(
                f"[blue][INFO][/blue] Backed up existing secrets: {backup_info.name} "
                f"({backup_info.key_count} keys, {backup_info.cert_count} certs)"
            )

        # Generate secrets
        orchestrator = SecretGenerationOrchestrator(
            config,
            console,
        )
        orchestrator.generate_all_secrets()

        # Generate PKI certificates if requested
        if pki:
            console.print("")
            console.print("[blue][INFO][/blue] Starting PKI certificate generation...")

            pki_gen = PKICertificateGenerator(secrets_manager)

            # Check if CA exists and warn appropriately
            if pki_gen.ca_certificates_exist() and not force_ca:
                console.print(
                    "[yellow][WARNING][/yellow] CA certificates already exist. "
                    "Use --force-ca to regenerate them."
                )
                console.print(
                    "[blue][INFO][/blue] Using existing CA certificates to generate service certificates..."
                )
            elif force_ca and pki_gen.ca_certificates_exist():
                console.print(
                    "[yellow][WARNING][/yellow] Force regenerating CA certificates "
                    "(existing ones will be backed up)"
                )

            result = pki_gen.generate_pki_certificates(force_ca=force_ca)

            # Display results
            if result.root_ca_generated:
                console.print(
                    "[green][SUCCESS][/green] Generated Root CA certificate and key"
                )
            if result.intermediate_ca_generated:
                console.print(
                    "[green][SUCCESS][/green] Generated Intermediate CA certificate and key"
                )
            for svc in result.services_generated:
                console.print(
                    f"[green][SUCCESS][/green] Generated certificate for {svc} service"
                )
            for svc in result.chains_created:
                console.print(
                    f"[green][SUCCESS][/green] Created certificate chains for {svc}"
                )
            if result.external_ca_included:
                console.print(
                    "[blue][INFO][/blue] Included external PostgreSQL CA certificate"
                )
            if result.ca_bundle_created:
                console.print(
                    "[green][SUCCESS][/green] Created CA bundle: certs/ca-bundle.crt"
                )

            console.print("")
            console.print(
                "[green][SUCCESS][/green] PKI certificate generation complete!"
            )
            console.print("[blue][INFO][/blue] Certificate hierarchy:")
            console.print(
                "[blue][INFO][/blue]   Root CA -> Intermediate CA -> Service Certificates"
            )
            console.print(
                "[yellow][WARNING][/yellow] Keep CA private keys secure and never commit them to version control!"
            )

        # Display success message
        console.print("")
        console.print(
            Panel(
                "[green]✅ Secrets generated successfully![/green]\n\n"
                "Generated files:\n"
                f"• Keys: {secrets_dir / 'keys'}\n"
                f"• Certificates: {secrets_dir / 'certs'}\n\n"
                "[yellow]⚠️  Important:[/yellow]\n"
                "• These secrets are for production use\n"
                "• Keep them secure and never commit to git\n"
                "• You may need to redeploy services to use new secrets",
                title="Success",
                border_style="green",
            )
        )

    except Exception as e:
        console.error(f"Error generating secrets: {e}")
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

    Shows which secrets have been generated, their file locations, sizes, and permissions.
    Use --show-values to display actual values (NOT recommended in shared environments).

    Examples:
        # List all secrets
        uv run api-forge-cli secrets list

        # Show secret values (be careful!)
        uv run api-forge-cli secrets list --show-values
    """
    project_root = Path(get_project_root())
    secrets_dir = project_root / "infra" / "secrets"
    secrets_manager = _get_file_secrets_manager(secrets_dir)

    # List secrets using SecretsManager
    console.print("[blue][INFO][/blue] Listing all secrets and certificates:")
    console.print("")
    console.print(f"{'Item':<45} {'Size':>10} {'Permissions':>10}")
    console.print(f"{'-' * 45} {'-' * 10} {'-' * 10}")

    files_found = False

    # List keys
    for key in secrets_manager.list_keys():
        result = secrets_manager.verify(key)
        if result.exists:
            size_str = f"{result.size} bytes" if result.size else "???"
            perms = result.permissions or "???"
            console.print(f"{key:<45} {size_str:>10} {perms:>10}")
            files_found = True

    # List certificates
    for cert in secrets_manager.list_certs():
        result = secrets_manager.verify(cert, SecretKind.CERT)
        if result.exists:
            size_str = f"{result.size} bytes" if result.size else "???"
            perms = result.permissions or "???"
            console.print(f"certs/{cert:<40} {size_str:>10} {perms:>10}")
            files_found = True

    if not files_found:
        console.warn("No secrets or certificates found")

    # If user wants to see values, create a separate table
    if show_values:
        console.print("\n[yellow]⚠️  Secret Values (handle with care!):[/yellow]\n")

        table = Table(title="🔐 Secret Values")
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="yellow")

        for key in secrets_manager.list_keys():
            try:
                value = secrets_manager.read(key) or ""
                # Truncate long values
                if len(value) > 40:
                    value = value[:40] + "..."
                table.add_row(key, value)
            except Exception as e:
                table.add_row(key, f"[red]Error: {e}[/red]")

        console.print(table)


@secrets_app.command()
def verify() -> None:
    """
    ✅ Verify that all required secrets exist and meet security requirements.

    Checks that all necessary secrets files are present, have correct permissions,
    and meet minimum length requirements. Also validates PKI certificates.

    Examples:
        # Verify all secrets
        uv run api-forge-cli secrets verify
    """
    project_root = Path(get_project_root())
    secrets_dir = project_root / "infra" / "secrets"
    secrets_manager = _get_file_secrets_manager(secrets_dir)

    console.print("[blue][INFO][/blue] Verifying existing secrets and certificates...")

    results = secrets_manager.verify_all()
    all_valid = True

    for result in results:
        if result.exists:
            if result.valid:
                expiry = ""
                if result.expires_at:
                    expiry = f", expires: {result.expires_at.strftime('%Y-%m-%d')}"
                console.print(
                    f"[green][SUCCESS][/green] {result.key}: OK "
                    f"({result.size} bytes, permissions: {result.permissions}{expiry})"
                )
            else:
                issues = ", ".join(result.issues)
                console.print(f"[yellow][WARNING][/yellow] {result.key}: {issues}")
                all_valid = False
        else:
            console.print(f"[yellow][WARNING][/yellow] {result.key}: Missing")
            all_valid = False

    if all_valid:
        console.print("[green][SUCCESS][/green] All secrets and certificates verified!")
    else:
        console.print(
            "[yellow][WARNING][/yellow] Some secrets or certificates need attention."
        )


@secrets_app.command()
def backup() -> None:
    """
    💾 Backup existing secrets to timestamped directory.

    Creates a backup of all secrets and certificates in a timestamped directory.
    Backups are stored in infra/secrets/backups/backup_YYYYMMDD_HHMMSS/.

    Examples:
        # Backup current secrets
        uv run api-forge-cli secrets backup
    """
    project_root = Path(get_project_root())
    secrets_dir = project_root / "infra" / "secrets"
    secrets_manager = _get_file_secrets_manager(secrets_dir)

    try:
        backup_info = secrets_manager.backup_all()
        console.print(
            Panel(
                f"[green]✅ Backup created successfully![/green]\n\n"
                f"Backup: {backup_info.name}\n"
                f"Keys: {backup_info.key_count}\n"
                f"Certificates: {backup_info.cert_count}\n\n"
                "[blue]ℹ️  Use 'secrets list-backups' to see all backups\n"
                "   Use 'secrets pop' to restore from most recent backup[/blue]",
                title="Backup Complete",
                border_style="green",
            )
        )
    except RuntimeError as e:
        console.error(f"Backup failed: {e}")
        raise typer.Exit(1) from e


@secrets_app.command()
def list_backups() -> None:
    """
    📋 List all available backup directories.

    Shows all timestamped backup directories with file counts and dates.

    Examples:
        # List all backups
        uv run api-forge-cli secrets list-backups
    """
    project_root = Path(get_project_root())
    secrets_dir = project_root / "infra" / "secrets"
    secrets_manager = _get_file_secrets_manager(secrets_dir)

    backups = secrets_manager.list_backups()

    if not backups:
        console.warn("No backups found")
        console.print("\n💡 Create a backup with: uv run api-forge-cli secrets backup")
        return

    console.print("")
    console.print("[blue][INFO][/blue] Available backups (newest first):")
    console.print("")

    table = Table()
    table.add_column("#", style="dim")
    table.add_column("Backup Name", style="cyan")
    table.add_column("Date", style="green")
    table.add_column("Keys", justify="right")
    table.add_column("Certs", justify="right")

    for idx, backup in enumerate(backups, start=1):
        table.add_row(
            str(idx),
            backup.name,
            backup.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            str(backup.key_count),
            str(backup.cert_count),
        )

    console.print(table)


@secrets_app.command()
def pop(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """
    ♻️  Restore secrets from the most recent backup and delete it.

    This command:
    1. Restores all secrets from the most recent backup
    2. Overwrites current secrets in keys/ and certs/
    3. Deletes the backup directory after successful restoration

    ⚠️  WARNING: This is a destructive operation!

    Examples:
        # Restore from most recent backup (with confirmation)
        uv run api-forge-cli secrets pop

        # Restore without confirmation prompt
        uv run api-forge-cli secrets pop --yes
    """
    project_root = Path(get_project_root())
    secrets_dir = project_root / "infra" / "secrets"
    secrets_manager = _get_file_secrets_manager(secrets_dir)

    latest = secrets_manager.get_latest_backup()

    if latest is None:
        console.error("No backups available to restore from")
        raise typer.Exit(1)

    # Show what will be restored
    console.print("")
    console.print(
        Panel(
            f"[yellow]⚠️  RESTORE FROM BACKUP[/yellow]\n\n"
            f"Backup: {latest.name}\n"
            f"Date: {latest.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Keys: {latest.key_count}\n"
            f"Certificates: {latest.cert_count}\n\n"
            "[red]Current secrets will be OVERWRITTEN.\n"
            "The backup will be DELETED after restoration.[/red]",
            title="Confirm Restore",
            border_style="yellow",
        )
    )

    # Confirm unless --yes flag is used
    if not yes:
        if not console.confirm_action(
            action="Restore from backup",
            details=f"Restore {latest.key_count} keys and {latest.cert_count} certs from {latest.name}",
            extra_warning="Current secrets will be overwritten!",
            force=False,
        ):
            console.print("[dim]Operation cancelled.[/dim]")
            raise typer.Exit(0)

    try:
        restored = secrets_manager.pop_backup()
        if restored:
            console.print(
                Panel(
                    f"[green]✅ Secrets restored successfully![/green]\n\n"
                    f"Restored from: {restored.name}\n"
                    f"Keys: {restored.key_count}\n"
                    f"Certificates: {restored.cert_count}\n\n"
                    "[blue]ℹ️  Run 'secrets verify' to verify the restored secrets[/blue]",
                    title="Restore Complete",
                    border_style="green",
                )
            )
    except (KeyError, RuntimeError) as e:
        console.error(f"Restore failed: {e}")
        raise typer.Exit(1) from e
