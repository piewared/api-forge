"""Validate configuration consistency across deployment targets."""

import typer
from rich.table import Table

from src.app.runtime.config.secrets_registry import (
    SECRETS,
    get_fly_secret_names,
    get_secrets_for_target,
)
from src.cli.shared.console import console
from src.utils.paths import get_project_root

config_app = typer.Typer(help="Configuration validation commands")


def _check_env_files() -> list[tuple[str, bool, str]]:
    """Check .env and .env.fly existence and basic content."""
    root = get_project_root()
    results: list[tuple[str, bool, str]] = []

    env_path = root / ".env"
    if env_path.exists():
        results.append((".env exists", True, ""))
        # Check it doesn't contain Fly.io internal addresses
        content = env_path.read_text()
        if ".internal:" in content:
            results.append(
                (
                    ".env has no Fly.io internal addresses",
                    False,
                    "Found .internal address — should be in .env.fly",
                )
            )
        else:
            results.append((".env has no Fly.io internal addresses", True, ""))
    else:
        results.append((".env exists", False, "File not found"))

    fly_path = root / ".env.fly"
    if fly_path.exists():
        results.append((".env.fly exists", True, ""))
    else:
        results.append(
            (
                ".env.fly exists",
                False,
                "Missing — Fly.io deploys may use wrong DB URL",
            )
        )

    return results


def _check_secrets_registry() -> list[tuple[str, bool, str]]:
    """Check secrets registry consistency."""
    results: list[tuple[str, bool, str]] = []

    # Verify all secrets have at least one target
    orphaned = [s for s in SECRETS if not s.targets]
    if orphaned:
        names = ", ".join(s.name for s in orphaned)
        results.append(
            (
                "All secrets have targets",
                False,
                f"Orphaned: {names}",
            )
        )
    else:
        results.append(("All secrets have targets", True, ""))

    # Verify secret files exist
    secrets_dir = get_project_root() / "infra" / "secrets" / "keys"
    fly_secrets = get_fly_secret_names()
    missing = [
        name for name in fly_secrets if not (secrets_dir / f"{name}.txt").exists()
    ]
    if missing:
        results.append(
            (
                "Fly.io secret files exist",
                False,
                f"Missing: {', '.join(missing)}",
            )
        )
    else:
        results.append(("Fly.io secret files exist", True, ""))

    return results


def _check_docker_compose_secrets() -> list[tuple[str, bool, str]]:
    """Check docker-compose.prod.yml secrets against registry."""
    results: list[tuple[str, bool, str]] = []
    compose_path = get_project_root() / "docker-compose.prod.yml"

    if not compose_path.exists():
        results.append(
            (
                "docker-compose.prod.yml exists",
                False,
                "File not found",
            )
        )
        return results

    content = compose_path.read_text()
    registry_secrets = get_secrets_for_target("docker-compose-prod")
    registry_names = {s.name for s in registry_secrets}

    # Simple heuristic: check for secret file references in compose
    for name in registry_names:
        if name not in content and name.upper() not in content:
            results.append(
                (
                    f"Compose references {name}",
                    False,
                    "Not found in docker-compose.prod.yml",
                )
            )

    if not any(not ok for _, ok, _ in results):
        results.append(
            (
                "Compose secrets match registry",
                True,
                f"{len(registry_names)} secrets declared",
            )
        )

    return results


@config_app.command("validate")
def validate(
    target: str | None = typer.Option(
        None,
        "--target",
        "-t",
        help="Check specific target: fly-io, kubernetes, docker-compose-prod",
    ),
) -> None:
    """Check for configuration drift between deployment targets."""
    all_checks: list[tuple[str, bool, str]] = []

    all_checks.extend(_check_env_files())
    all_checks.extend(_check_secrets_registry())
    all_checks.extend(_check_docker_compose_secrets())

    table = Table(title="Configuration Validation")
    table.add_column("Check", style="cyan")
    table.add_column("Status", width=6)
    table.add_column("Detail", style="dim")

    passed = 0
    failed = 0
    for check_name, ok, detail in all_checks:
        if target and target not in check_name.lower():
            continue
        status = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
        if ok:
            passed += 1
        else:
            failed += 1
        table.add_row(check_name, status, detail)

    console.console.print(table)
    console.info(f"{passed} passed, {failed} failed")

    if failed:
        raise typer.Exit(code=1)
