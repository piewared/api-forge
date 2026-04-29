# Fly.io CLI Implementation Plan

> **Status**: Implementation Plan  
> **Created**: January 2, 2026  
> **Target**: `api-forge-cli fly db` commands with Fly Postgres support

---

## 1. Overview

This document outlines the implementation plan for adding Fly.io deployment support to the `api-forge-cli`. The initial phase focuses on database management commands (`fly db`) with plans to expand to full deployment lifecycle commands in future iterations.

### 1.1 Goals

1. Create a `FlyCtlController` abstraction over the `flyctl` CLI tool
2. Implement `fly auth` commands for authentication management
3. Implement `fly db` commands mirroring the existing `k8s db` functionality
4. Support both Fly Postgres (managed) and bundled PostgreSQL deployments
5. Maximize code reuse with existing database workflows

### 1.2 Scope

**In Scope (This PR)**:
- `FlyCtlController` class (abstraction over `flyctl` CLI)
- `fly auth` commands (login, logout, status/whoami)
- `fly db` commands:
  - `create` - Create/configure PostgreSQL (managed or bundled)
  - `init` - Initialize database with roles and schema
  - `verify` - Verify database setup and configuration
  - `sync` - Synchronize PostgreSQL role passwords
  - `backup` - Create database backup
  - `reset` - Reset database to clean state
  - `status` - Show health and performance metrics
  - `migrate` - Manage Alembic migrations

**Out of Scope (Future PRs)**:
- `fly up/down/status` deployment commands
- FKS (Fly Kubernetes Service) integration
- Bundled PostgreSQL via custom Fly.io app deployment

---

## 2. Architecture

### 2.1 High-Level Architecture

```
src/cli/
├── commands/
│   ├── fly.py              # Main fly command group (existing, to be expanded)
│   ├── fly_auth.py         # NEW: fly auth subcommands
│   ├── fly_db.py           # NEW: fly db subcommands
│   └── db/
│       ├── runtime.py      # DbRuntime base class
│       ├── runtime_fly.py  # NEW: Fly.io runtime adapter
│       └── workflows.py    # Shared DB workflows (reuse existing)
└── shared/
    └── console.py          # CLI console utilities (existing)

src/infra/
├── flyio/                  # NEW: Fly.io infrastructure module
│   ├── __init__.py
│   ├── controller.py       # FlyCtlController + FlyCtlControllerSync + stub generation
│   ├── controller.pyi      # Auto-generated type stubs (run: python -m src.infra.flyio.controller)
│   ├── constants.py        # Fly.io specific constants
│   └── postgres_connection.py  # Fly Postgres connection helper
└── postgres/               # Existing PostgreSQL utilities (reuse)
```

### 2.2 Component Relationships

```
┌─────────────────────────────────────────────────────────────────┐
│                     CLI Commands Layer                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │  fly auth   │  │   fly db    │  │      fly (future)       │ │
│  │   login     │  │   create    │  │    up/down/status       │ │
│  │   logout    │  │   init      │  │                         │ │
│  │   whoami    │  │   verify    │  │                         │ │
│  └──────┬──────┘  │   ...       │  └─────────────────────────┘ │
│         │         └──────┬──────┘                               │
└─────────┼────────────────┼──────────────────────────────────────┘
          │                │
          ▼                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Infrastructure Layer                           │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │               FlyCtlController                             │  │
│  │                                                           │  │
│  │  Low-level (private):                                     │  │
│  │  - _run_flyctl()      Execute flyctl subprocess           │  │
│  │  - _run_flyctl_json() Execute + parse JSON output         │  │
│  │                                                           │  │
│  │  High-level (public):                                     │  │
│  │  - auth_login()       - mpg_create()                      │  │
│  │  - auth_logout()      - mpg_list() -> [ManagedPgInfo]     │  │
│  │  - auth_whoami()      - mpg_status()                      │  │
│  │  - is_authenticated() - mpg_backup_create()               │  │
│  │  - secrets_set()      - postgres_create() (legacy)        │  │
│  │  - secrets_list()     - proxy()                           │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      flyctl CLI                                  │
│              (External dependency, must be installed)            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Design

### 3.1 FlyCtlController

Located at: `src/infra/flyio/controller.py`

This controller follows the same pattern as `KubectlController` - a single class that both
executes flyctl commands and parses the output into typed dataclasses.

```python
"""Fly.io controller using flyctl CLI commands."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    """Result of a command execution."""
    success: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


@dataclass
class ManagedPostgresInfo:
    """Information about a Fly Managed Postgres cluster."""
    id: str
    name: str
    region: str
    plan: str
    status: str
    created_at: str
    connection_string: str | None = None


@dataclass
class FlyAppInfo:
    """Information about a Fly.io application."""
    name: str
    organization: str
    status: str
    hostname: str


class FlyCtlController:
    """Controller for Fly.io operations via flyctl CLI.
    
    This class provides both low-level command execution and high-level
    operations that parse output into typed dataclasses.
    
    Design follows the same patterns as KubectlController for consistency:
    - All methods are async (use asyncio.to_thread for subprocess calls)
    - Low-level _run_flyctl() for raw command execution
    - High-level methods return parsed dataclasses where appropriate
    
    Example:
        controller = FlyCtlController()
        
        # Check authentication
        if await controller.is_authenticated():
            clusters = await controller.mpg_list()
            for cluster in clusters:
                print(f"{cluster.name} ({cluster.region}): {cluster.status}")
    """
    
    # =========================================================================
    # Low-level command execution (private)
    # =========================================================================
    
    async def _run_flyctl(
        self,
        args: list[str],
        *,
        capture_output: bool = True,
        input_data: str | None = None,
    ) -> CommandResult:
        """Run a flyctl command asynchronously.
        
        Args:
            args: Command arguments (without 'fly' prefix)
            capture_output: Whether to capture stdout/stderr
            input_data: Optional input to send to stdin
        
        Returns:
            CommandResult with execution results
        """
        import subprocess
        
        cmd = ["fly", *args]
        
        def _run() -> CommandResult:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                input=input_data,
            )
            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                returncode=result.returncode,
            )
        
        return await asyncio.to_thread(_run)
    
    async def _run_flyctl_json(
        self,
        args: list[str],
    ) -> tuple[bool, dict | list | None]:
        """Run a flyctl command and parse JSON output.
        
        Args:
            args: Command arguments (--json flag added automatically)
        
        Returns:
            Tuple of (success, parsed_json_or_none)
        """
        result = await self._run_flyctl([*args, "--json"])
        if result.success and result.stdout:
            try:
                return True, json.loads(result.stdout)
            except json.JSONDecodeError:
                return False, None
        return False, None
    
    # =========================================================================
    # Authentication
    # =========================================================================
    
    async def auth_login(self, interactive: bool = False) -> CommandResult:
        """Log in to Fly.io.
        
        Args:
            interactive: Use email/password instead of browser
        """
        args = ["auth", "login"]
        if interactive:
            args.append("--interactive")
        return await self._run_flyctl(args)
    
    async def auth_logout(self) -> CommandResult:
        """Log out from Fly.io."""
        return await self._run_flyctl(["auth", "logout"])
    
    async def auth_whoami(self) -> tuple[bool, str]:
        """Get current authenticated user.
        
        Returns:
            Tuple of (is_authenticated, email_or_error_message)
        """
        result = await self._run_flyctl(["auth", "whoami"])
        return result.success, result.stdout.strip() if result.success else result.stderr.strip()
    
    async def is_authenticated(self) -> bool:
        """Check if user is authenticated."""
        success, _ = await self.auth_whoami()
        return success
    
    # =========================================================================
    # Managed Postgres (MPG)
    # =========================================================================
    
    async def mpg_create(
        self,
        name: str,
        region: str,
        plan: str = "basic",
        org: str | None = None,
        volume_size: int = 10,
        pgvector: bool = False,
    ) -> CommandResult:
        """Create a Fly Managed Postgres cluster."""
        args = ["mpg", "create", "--name", name, "--region", region, "--plan", plan]
        args.extend(["--volume-size", str(volume_size)])
        if org:
            args.extend(["--org", org])
        if pgvector:
            args.append("--pgvector")
        return await self._run_flyctl(args)
    
    async def mpg_list(self, org: str | None = None) -> list[ManagedPostgresInfo]:
        """List Managed Postgres clusters.
        
        Returns:
            List of ManagedPostgresInfo dataclasses
        """
        args = ["mpg", "list"]
        if org:
            args.extend(["--org", org])
        
        success, data = await self._run_flyctl_json(args)
        if not success or not isinstance(data, list):
            return []
        
        return [
            ManagedPostgresInfo(
                id=item.get("id", ""),
                name=item.get("name", ""),
                region=item.get("region", ""),
                plan=item.get("plan", ""),
                status=item.get("status", ""),
                created_at=item.get("created_at", ""),
                connection_string=item.get("connection_string"),
            )
            for item in data
        ]
    
    async def mpg_status(self, cluster_id: str) -> ManagedPostgresInfo | None:
        """Get status of a Managed Postgres cluster."""
        success, data = await self._run_flyctl_json(["mpg", "status", cluster_id])
        if not success or not isinstance(data, dict):
            return None
        
        return ManagedPostgresInfo(
            id=data.get("id", ""),
            name=data.get("name", ""),
            region=data.get("region", ""),
            plan=data.get("plan", ""),
            status=data.get("status", ""),
            created_at=data.get("created_at", ""),
            connection_string=data.get("connection_string"),
        )
    
    async def mpg_connect(self, cluster_id: str) -> CommandResult:
        """Open psql connection to cluster (interactive)."""
        return await self._run_flyctl(["mpg", "connect", cluster_id])
    
    async def mpg_proxy(self, cluster_id: str) -> CommandResult:
        """Start local proxy to cluster."""
        return await self._run_flyctl(["mpg", "proxy", cluster_id])
    
    async def mpg_attach(self, cluster_id: str, app_name: str) -> CommandResult:
        """Attach a Fly app to the cluster (sets DATABASE_URL secret)."""
        return await self._run_flyctl(["mpg", "attach", cluster_id, "-a", app_name])
    
    async def mpg_backup_create(self, cluster_id: str) -> CommandResult:
        """Create a backup of the cluster."""
        return await self._run_flyctl(["mpg", "backup", "create", cluster_id])
    
    async def mpg_backup_list(self, cluster_id: str) -> list[dict]:
        """List backups for a cluster."""
        success, data = await self._run_flyctl_json(["mpg", "backup", "list", cluster_id])
        if success and isinstance(data, list):
            return data
        return []
    
    async def mpg_restore(self, cluster_id: str, backup_id: str) -> CommandResult:
        """Restore cluster from a backup."""
        return await self._run_flyctl(["mpg", "restore", cluster_id, "--backup-id", backup_id])
    
    async def mpg_destroy(self, cluster_id: str, confirm: bool = False) -> CommandResult:
        """Destroy a Managed Postgres cluster."""
        args = ["mpg", "destroy", cluster_id]
        if confirm:
            args.append("--yes")
        return await self._run_flyctl(args)
    
    # =========================================================================
    # Legacy Postgres (unmanaged Fly Postgres)
    # =========================================================================
    
    async def postgres_create(
        self,
        name: str,
        region: str,
        org: str | None = None,
    ) -> CommandResult:
        """Create an unmanaged Fly Postgres cluster."""
        args = ["postgres", "create", "--name", name, "--region", region]
        if org:
            args.extend(["--org", org])
        return await self._run_flyctl(args)
    
    async def postgres_list(self) -> list[dict]:
        """List unmanaged Postgres clusters."""
        success, data = await self._run_flyctl_json(["postgres", "list"])
        if success and isinstance(data, list):
            return data
        return []
    
    async def postgres_connect(self, app_name: str) -> CommandResult:
        """Connect to unmanaged Postgres cluster."""
        return await self._run_flyctl(["postgres", "connect", "-a", app_name])
    
    # =========================================================================
    # Secrets Management
    # =========================================================================
    
    async def secrets_set(
        self,
        app_name: str,
        secrets: dict[str, str],
        stage: bool = False,
    ) -> CommandResult:
        """Set secrets for a Fly app.
        
        Args:
            app_name: Target app name
            secrets: Dict of secret_name -> secret_value
            stage: If True, stage secrets without redeploying
        """
        args = ["secrets", "set"]
        args.extend([f"{k}={v}" for k, v in secrets.items()])
        args.extend(["-a", app_name])
        if stage:
            args.append("--stage")
        return await self._run_flyctl(args)
    
    async def secrets_list(self, app_name: str) -> list[str]:
        """List secret names for a Fly app (values are not shown)."""
        result = await self._run_flyctl(["secrets", "list", "-a", app_name])
        if not result.success:
            return []
        # Parse output - format is "NAME | DIGEST | DATE"
        lines = result.stdout.strip().split("\n")
        names = []
        for line in lines[1:]:  # Skip header
            parts = line.split("|")
            if parts:
                names.append(parts[0].strip())
        return names
    
    async def secrets_unset(self, app_name: str, names: list[str]) -> CommandResult:
        """Remove secrets from a Fly app."""
        return await self._run_flyctl(["secrets", "unset", *names, "-a", app_name])
    
    # =========================================================================
    # Apps
    # =========================================================================
    
    async def apps_list(self, org: str | None = None) -> list[FlyAppInfo]:
        """List Fly apps."""
        args = ["apps", "list"]
        if org:
            args.extend(["--org", org])
        
        success, data = await self._run_flyctl_json(args)
        if not success or not isinstance(data, list):
            return []
        
        return [
            FlyAppInfo(
                name=item.get("name", ""),
                organization=item.get("organization", ""),
                status=item.get("status", ""),
                hostname=item.get("hostname", ""),
            )
            for item in data
        ]
    
    async def app_info(self, app_name: str) -> FlyAppInfo | None:
        """Get info about a specific app."""
        success, data = await self._run_flyctl_json(["apps", "info", app_name])
        if not success or not isinstance(data, dict):
            return None
        
        return FlyAppInfo(
            name=data.get("name", ""),
            organization=data.get("organization", ""),
            status=data.get("status", ""),
            hostname=data.get("hostname", ""),
        )
    
    # =========================================================================
    # Utilities
    # =========================================================================
    
    async def is_installed(self) -> bool:
        """Check if flyctl CLI is installed."""
        import shutil
        return shutil.which("fly") is not None or shutil.which("flyctl") is not None


# =============================================================================
# Synchronous Wrapper (Dynamic)
# =============================================================================


class FlyCtlControllerSync:
    """Synchronous wrapper for FlyCtlController.

    Automatically wraps all async methods from the underlying controller
    and exposes them as synchronous methods using run_sync().
    """

    def __init__(self, controller: FlyCtlController | None = None):
        self._controller = controller or FlyCtlController()

    def __getattr__(self, name: str):
        """Dynamically wrap async methods as sync."""
        from src.infra.k8s.utils import run_sync
        import inspect
        
        attr = getattr(self._controller, name)
        if callable(attr) and inspect.iscoroutinefunction(attr):
            def sync_wrapper(*args, **kwargs):
                return run_sync(attr(*args, **kwargs))
            return sync_wrapper
        return attr


# =============================================================================
# Stub File Generation
# =============================================================================


def generate_sync_stubs() -> str:
    """Generate a .pyi stub file for FlyCtlControllerSync.
    
    Follows the same pattern as KubernetesController stub generation.
    Extracts dataclass definitions and method signatures via AST/inspect.
    """
    # Implementation mirrors src/infra/k8s/controller.py generate_sync_stubs()
    # See that file for the full AST-based stub generation logic
    ...


if __name__ == "__main__":
    """Generate FlyCtlControllerSync stub file."""
    from pathlib import Path

    stub_content = generate_sync_stubs()
    stub_path = Path(__file__).with_suffix(".pyi")
    stub_path.write_text(stub_content)

    print(f"✅ Generated type stubs: {stub_path}")
    print(f"📝 {len(stub_content.splitlines())} lines")
    print("\nTo use the synchronous wrapper with full type hints:")
    print("  from src.infra.flyio.controller import FlyCtlControllerSync")
    print("")
    print("  sync_controller = FlyCtlControllerSync()")
    print("  clusters = sync_controller.mpg_list()  # Fully typed!")
```

> **Note**: The `FlyCtlControllerSync` wrapper and stub generation are included directly in `controller.py`
> (shown above), following the exact same pattern as `src/infra/k8s/controller.py`. After modifying
> `FlyCtlController`, regenerate type stubs by running `python -m src.infra.flyio.controller`.

### 3.3 Fly.io Database Runtime

Located at: `src/cli/commands/db/runtime_fly.py`

```python
"""Fly.io database runtime adapter."""

from contextlib import contextmanager
from pathlib import Path

from src.cli.commands.db.runtime import DbRuntime, no_port_forward
from src.cli.context import get_cli_context
from src.cli.shared.console import console

def get_fly_runtime() -> DbRuntime:
    """Create a Fly.io-specific database runtime.
    
    Reuses existing workflow functions but provides Fly.io-specific:
    - Connection handling via flyctl proxy
    - Settings retrieval from Fly secrets
    - Fly Managed Postgres status checks
    """
    from src.app.runtime.config import get_settings
    from src.infra.postgres import get_postgres_connection
    
    @contextmanager
    def fly_port_forward():
        """Create a proxy tunnel to Fly Postgres.
        
        Uses `fly mpg proxy` or `fly proxy` depending on whether
        we're connecting to Managed Postgres or unmanaged Postgres.
        """
        ctx = get_cli_context()
        # Implementation will detect cluster type and start appropriate proxy
        # This is a placeholder - actual implementation requires async handling
        yield
    
    def is_fly_bundled_postgres_enabled() -> bool:
        """Check if bundled (unmanaged) Postgres is configured for Fly."""
        # Will check config.yaml for fly.postgres.bundled = true
        return False
    
    def get_fly_deployer():
        """Get the Fly.io deployer (placeholder for future)."""
        return None
    
    return DbRuntime(
        name="fly",
        console=console,
        get_settings=get_settings,
        connect=get_postgres_connection,
        port_forward=fly_port_forward,
        get_deployer=get_fly_deployer,
        secrets_dirs=[
            Path("infra/secrets/keys"),
        ],
        is_temporal_enabled=lambda: False,  # Temporal not supported on Fly yet
        is_bundled_postgres_enabled=is_fly_bundled_postgres_enabled,
    )
```

### 3.4 CLI Commands

#### 3.4.1 fly auth commands (`src/cli/commands/fly_auth.py`)

```python
"""Fly.io authentication commands."""

import typer
from src.cli.shared.console import console, with_error_handling
from src.cli.context import get_cli_context

fly_auth_app = typer.Typer(
    name="auth",
    help="Fly.io authentication commands.",
    no_args_is_help=True,
)

@fly_auth_app.command()
@with_error_handling
def login(
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Log in with email and password interactively",
    ),
) -> None:
    """Log in to Fly.io.
    
    Opens a browser for authentication by default.
    Use --interactive for email/password login.
    
    Examples:
        uv run api-forge-cli fly auth login
        uv run api-forge-cli fly auth login --interactive
    """
    ...

@fly_auth_app.command()
@with_error_handling
def logout() -> None:
    """Log out from Fly.io.
    
    Examples:
        uv run api-forge-cli fly auth logout
    """
    ...

@fly_auth_app.command()
@with_error_handling
def whoami() -> None:
    """Show current Fly.io authentication status.
    
    Displays the currently authenticated user's email and organization.
    
    Examples:
        uv run api-forge-cli fly auth whoami
    """
    ...
```

#### 3.4.2 fly db commands (`src/cli/commands/fly_db.py`)

```python
"""PostgreSQL database management for Fly.io deployments."""

import typer
from typing import Annotated
from pathlib import Path

from src.cli.commands.db import (
    DbRuntime,
    run_backup,
    run_init,
    run_migrate,
    run_reset,
    run_status,
    run_sync,
    run_verify,
)
from src.cli.commands.db.runtime_fly import get_fly_runtime
from src.cli.shared.console import console, with_error_handling

fly_db_app = typer.Typer(
    name="db",
    help="PostgreSQL database management for Fly.io.",
    no_args_is_help=True,
)

def _get_runtime() -> DbRuntime:
    """Return the Fly.io DB runtime."""
    return get_fly_runtime()

@fly_db_app.command()
@with_error_handling
def create(
    # Mode selection
    managed: Annotated[bool, typer.Option(
        "--managed",
        help="Create Fly Managed Postgres cluster (default)",
    )] = True,
    bundled: Annotated[bool, typer.Option(
        "--bundled",
        help="Deploy bundled PostgreSQL to Fly.io (unmanaged)",
    )] = False,
    # Managed Postgres options
    name: Annotated[str | None, typer.Option(
        "--name", "-n",
        help="Cluster name (generated if not provided)",
    )] = None,
    region: Annotated[str, typer.Option(
        "--region", "-r",
        help="Fly.io region (e.g., iad, lhr, sin)",
    )] = "iad",
    plan: Annotated[str, typer.Option(
        "--plan", "-p",
        help="MPG plan: basic, starter, launch, scale, performance",
    )] = "basic",
    org: Annotated[str | None, typer.Option(
        "--org", "-o",
        help="Fly.io organization",
    )] = None,
    volume_size: Annotated[int, typer.Option(
        "--volume-size",
        help="Storage size in GB (default: 10)",
    )] = 10,
    pgvector: Annotated[bool, typer.Option(
        "--pgvector",
        help="Enable PGVector extension",
    )] = False,
) -> None:
    """Create PostgreSQL database for Fly.io deployment.
    
    Two modes are available:
    
    --managed (default): Create a Fly Managed Postgres (MPG) cluster.
    This is a fully managed database service with automatic backups,
    high availability, and performance monitoring.
    
    --bundled: Deploy bundled PostgreSQL as a Fly app (unmanaged).
    This gives you more control but requires self-management.
    
    Examples:
        # Create managed Postgres with defaults
        uv run api-forge-cli fly db create
        
        # Create managed Postgres with custom settings
        uv run api-forge-cli fly db create --name my-db --region lhr --plan starter
        
        # Create with PGVector extension
        uv run api-forge-cli fly db create --pgvector
        
        # Deploy bundled (unmanaged) Postgres
        uv run api-forge-cli fly db create --bundled
    """
    ...

@fly_db_app.command()
@with_error_handling  
def init() -> None:
    """Initialize the PostgreSQL database with roles and schema.
    
    Creates application roles (appuser, appowner, backupuser) and
    initializes the database schema.
    
    Examples:
        uv run api-forge-cli fly db init
    """
    console.print_header("Initializing PostgreSQL Database (Fly.io)")
    success = run_init(_get_runtime(), superuser_mode=True)
    if not success:
        raise typer.Exit(1)
    console.print("\n[bold green]🎉 Database initialization complete![/bold green]")

@fly_db_app.command()
@with_error_handling
def verify() -> None:
    """Verify PostgreSQL database setup and configuration.
    
    Checks connectivity, roles, permissions, and schema state.
    
    Examples:
        uv run api-forge-cli fly db verify
    """
    console.print_header("Verifying PostgreSQL Database (Fly.io)")
    success = run_verify(_get_runtime(), superuser_mode=True)
    if not success:
        raise typer.Exit(1)
    console.print("\n[bold green]✓ Database verification passed![/bold green]")

@fly_db_app.command()
@with_error_handling
def sync() -> None:
    """Synchronize PostgreSQL role passwords.
    
    Updates database role passwords to match current secrets.
    
    Examples:
        uv run api-forge-cli fly db sync
    """
    console.print_header("Synchronizing PostgreSQL Passwords (Fly.io)")
    success = run_sync(_get_runtime(), superuser_mode=True)
    if not success:
        raise typer.Exit(1)
    console.print("\n[bold green]✓ Password synchronization complete![/bold green]")

@fly_db_app.command()
@with_error_handling
def backup(
    output_dir: Annotated[Path | None, typer.Option(
        "--output-dir", "-o",
        help="Directory to save backup file",
    )] = None,
) -> None:
    """Create a PostgreSQL database backup.
    
    For Managed Postgres, uses Fly.io's built-in backup system.
    For bundled Postgres, creates a pg_dump backup file.
    
    Examples:
        uv run api-forge-cli fly db backup
        uv run api-forge-cli fly db backup --output-dir ./backups
    """
    console.print_header("Creating PostgreSQL Backup (Fly.io)")
    backup_dir = output_dir or Path("./data/postgres-backups")
    success, result = run_backup(
        _get_runtime(),
        output_dir=backup_dir,
        superuser_mode=True,
    )
    if not success:
        console.error(f"Backup failed: {result}")
        raise typer.Exit(1)
    console.print(f"\n[bold green]🎉 Backup created: {result}[/bold green]")

@fly_db_app.command()
@with_error_handling
def reset(
    yes: Annotated[bool, typer.Option(
        "--yes", "-y",
        help="Skip confirmation prompt",
    )] = False,
) -> None:
    """Reset the PostgreSQL database to clean state (DESTRUCTIVE).
    
    WARNING: This will permanently delete all database data!
    
    Examples:
        uv run api-forge-cli fly db reset
        uv run api-forge-cli fly db reset -y
    """
    console.print_header("Resetting PostgreSQL Database (Fly.io)")
    
    if not yes:
        if not console.confirm_action(
            "Reset PostgreSQL database",
            "This will permanently delete all database data!",
        ):
            console.print("[dim]Operation cancelled[/dim]")
            raise typer.Exit(0)
    
    success = run_reset(
        _get_runtime(),
        include_temporal=False,  # Temporal not supported on Fly yet
        superuser_mode=True,
    )
    if not success:
        raise typer.Exit(1)
    console.print("\n[bold green]🎉 Database reset complete![/bold green]")

@fly_db_app.command()
@with_error_handling
def status() -> None:
    """Show PostgreSQL health and performance metrics.
    
    Displays connection info, database sizes, and performance stats.
    
    Examples:
        uv run api-forge-cli fly db status
    """
    console.print_header("PostgreSQL Health & Performance (Fly.io)")
    run_status(_get_runtime(), superuser_mode=True)

@fly_db_app.command()
@with_error_handling
def migrate(
    action: Annotated[str, typer.Argument(
        help="Migration action: upgrade, downgrade, current, history, revision, heads, merge, show, stamp",
    )],
    revision: Annotated[str | None, typer.Argument(
        help="Target revision or message",
    )] = None,
    # ... (same options as k8s db migrate)
) -> None:
    """Manage database schema migrations with Alembic.
    
    Examples:
        uv run api-forge-cli fly db migrate upgrade
        uv run api-forge-cli fly db migrate downgrade abc123
        uv run api-forge-cli fly db migrate current
    """
    run_migrate(
        _get_runtime(),
        action=action,
        revision=revision,
        # ... pass through other options
    )
```

---

## 4. Implementation Order

### Phase 1: Foundation (PR #1)

1. **Create Fly.io infrastructure module**
   - `src/infra/flyio/__init__.py`
   - `src/infra/flyio/constants.py`
   - `src/infra/flyio/controller.py` (includes FlyCtlController, FlyCtlControllerSync, and stub generation)

2. **Generate type stubs**
   - Run `python -m src.infra.flyio.controller` to generate `controller.pyi`
   - Commit the generated `.pyi` file for IDE type hints

3. **Implement authentication commands**
   - `src/cli/commands/fly_auth.py`
   - Commands: `login`, `logout`, `whoami`

4. **Update CLI registration**
   - Update `src/cli/commands/fly.py` to include auth subcommand
   - Update `src/cli/__main__.py` or main CLI registration

### Phase 2: Database Commands (PR #2)

5. **Create Fly.io database runtime**
   - `src/cli/commands/db/runtime_fly.py`
   - Update `src/cli/commands/db/__init__.py`

6. **Implement fly db commands**
   - `src/cli/commands/fly_db.py`
   - Commands: `create`, `init`, `verify`, `sync`, `backup`, `reset`, `status`, `migrate`

7. **Update CLI context**
   - Add `fly_controller` to `CLIContext` in `src/cli/context.py`

### Phase 3: Testing & Documentation (PR #3)

8. **Add unit tests**
   - `tests/unit/cli/commands/test_fly_auth.py`
   - `tests/unit/cli/commands/test_fly_db.py`
   - `tests/unit/infra/flyio/test_controller.py`

9. **Add integration tests**
   - `tests/integration/cli/test_fly_commands.py` (requires `flyctl` installed)

10. **Update documentation**
    - Update `docs/fastapi-flyio-kubernetes.md`
    - Add `docs/fly-io-database.md`

---

## 5. Flyctl Command Mapping

| CLI Command | flyctl Command | Notes |
|-------------|----------------|-------|
| `fly auth login` | `fly auth login` | Browser-based by default |
| `fly auth logout` | `fly auth logout` | |
| `fly auth whoami` | `fly auth whoami` | Returns email/identity |
| `fly db create --managed` | `fly mpg create` | Fly Managed Postgres |
| `fly db create --bundled` | `fly postgres create` | Legacy unmanaged |
| `fly db status` | `fly mpg status` | + custom SQL queries |
| `fly db backup` | `fly mpg backup create` | MPG built-in backups |
| N/A | `fly mpg connect` | Opens psql session |
| N/A | `fly mpg proxy` | Local port forward |
| N/A | `fly mpg attach` | Attach app to cluster |
| `fly secrets set` | `fly secrets set` | For DATABASE_URL etc |

---

## 6. Configuration

### 6.1 config.yaml additions

```yaml
# Fly.io configuration (new section)
flyio:
  enabled: false
  organization: null  # Default org for commands
  app_name: "api-forge"
  region: "iad"
  
  postgres:
    type: "managed"  # "managed" or "bundled"
    cluster_name: null  # MPG cluster name/ID
    plan: "basic"
    volume_size: 10
    pgvector: false
```

### 6.2 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FLY_API_TOKEN` | Fly.io API token (for CI/CD) | None |
| `FLY_ORG` | Default organization | None |
| `FLY_REGION` | Default region | `iad` |
| `DATABASE_URL` | Postgres connection string | Set by `fly mpg attach` |

---

## 7. Error Handling

### 7.1 Common Errors

| Error | Cause | Resolution |
|-------|-------|------------|
| `flyctl not found` | flyctl not installed | Prompt user to install |
| `not authenticated` | No valid auth token | Run `fly auth login` |
| `organization not found` | Invalid org specified | List orgs, prompt selection |
| `cluster not found` | Invalid cluster ID | Run `fly mpg list` |
| `connection refused` | Proxy not running | Start `fly mpg proxy` |

### 7.2 Pre-flight Checks

All `fly db` commands should check:
1. `flyctl` is installed and in PATH
2. User is authenticated (`fly auth whoami`)
3. Target cluster exists (for commands that need it)
4. Proxy tunnel is established (for DB operations)

---

## 8. Testing Strategy

### 8.1 Unit Tests

- Mock `flyctl` subprocess calls
- Test command parsing and validation
- Test error handling paths
- Test configuration loading

### 8.2 Integration Tests

- Require `flyctl` installed
- Use test Fly.io organization
- Create/destroy test MPG clusters
- Mark as `@pytest.mark.flyio` for CI filtering

### 8.3 Manual Tests

- Full workflow: create → init → verify → backup → reset
- Both managed and bundled Postgres paths
- Authentication flow (browser-based)

---

## 9. Future Considerations

### 9.1 FKS Integration

When adding `fly up/down/status` commands:
- Detect if FKS cluster is available
- Reuse existing Helm charts with FKS-specific values
- Consider context switching between FKS and direct Fly.io

### 9.2 Bundled Postgres on Fly.io

For `--bundled` flag:
- Deploy our custom Postgres Docker image as Fly app
- Use Fly Volumes for data persistence
- Configure using `fly.toml` template
- Consider reusing `infra/docker/prod/postgres/` configuration

### 9.3 Redis Support

Future `fly db` commands could include:
- `fly db redis create` using Upstash for Redis
- Configuration in `config.yaml` under `flyio.redis`

---

## 10. References

### Fly.io Documentation
- [Fly.io Managed Postgres](https://fly.io/docs/mpg/)
- [MPG Create and Connect](https://fly.io/docs/mpg/create-and-connect/)
- [flyctl mpg commands](https://fly.io/docs/flyctl/mpg/)
- [flyctl auth commands](https://fly.io/docs/flyctl/auth/)
- [Fly.io Secrets](https://fly.io/docs/apps/secrets/)
- [Fly Kubernetes (FKS)](https://fly.io/docs/kubernetes/)

### Existing Codebase
- [k8s.py](../src/cli/commands/k8s.py) - K8s command patterns
- [k8s_db.py](../src/cli/commands/k8s_db.py) - K8s database commands
- [kubectl_controller.py](../src/infra/k8s/kubectl_controller.py) - Controller patterns
- [runtime.py](../src/cli/commands/db/runtime.py) - DbRuntime base class
