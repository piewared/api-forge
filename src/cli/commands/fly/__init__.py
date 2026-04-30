"""Fly.io deployment commands.

This package provides Fly.io deployment commands for traditional Fly.io
deployments using `fly deploy` and Fly Machines.

Commands match the k8s workflow:
- up: Create app (if needed), generate fly.toml (if needed), deploy
- down: Tear down the deployment
- status: Show deployment status
- logs: View logs

Additional commands:
- scale: Adjust machine count, VM size, memory
- machines: List/manage individual machines
- apps: List all Fly.io apps

For FKS (Fly Kubernetes Service) deployments, see the fks module (currently
in private beta - not generally available).
"""

import typer

from src.cli.commands.fly_auth import fly_auth_app
from src.cli.commands.fly_db import fly_db_app

# Define fly_app before importing submodules so their @fly_app.command()
# decorators can resolve it from the partially-initialized package.
fly_app = typer.Typer(
    name="fly",
    help="Fly.io deployment commands.",
    no_args_is_help=True,
)

# Register sub-typers before loading submodules (order matters for the CLI tree)
fly_app.add_typer(fly_auth_app, name="auth")
fly_app.add_typer(fly_db_app, name="db")

# Import submodules after fly_app is defined so their @fly_app.command()
# decorators succeed when they do `from . import fly_app`.
from src.cli.commands.fly import (  # noqa: F401, E402
    down,
    logs,
    machines,
    scale,
    status,
    sync,
    up,
)


# ---------------------------------------------------------------------------
# Quick-iteration entry point  (python -m src.cli.commands.fly)
# ---------------------------------------------------------------------------
# Routes directly into `fly up --service <svc>` so there is a single code
# path for both normal CLI usage and local test runs — no drift.
#
# Usage (no extra args needed):
#   PYTHONPATH=src python -m src.cli.commands.fly
#
# Override defaults via env vars:
#   FLY_TEST_SERVICE  — service to deploy (default: temporal)
#                       choices: redis, temporal, temporal-web, worker, app
#   FLY_TEST_REGION   — Fly region override
#   FLY_SKIP_DB_CHECK — set to "1" to add --skip-db-check
#
# Or pass Typer args directly:
#   PYTHONPATH=src python -m src.cli.commands.fly up --service redis
#   PYTHONPATH=src python -m src.cli.commands.fly up --service temporal --skip-db-check
# ---------------------------------------------------------------------------
