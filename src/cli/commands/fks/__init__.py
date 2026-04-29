"""Fly.io Kubernetes Service (FKS) deployment commands.

FKS is currently in private beta. Code preserved here for future use; for
traditional Fly.io deployment use ``src.cli.commands.fly`` instead.

Package layout mirrors ``src.cli.commands.fly``:

- ``_helpers.py`` — config loading, name generation, kubeconfig handling
- ``clusters.py`` — ``clusters`` / ``cluster-create`` / ``cluster-destroy``
- ``deploy.py``   — ``up`` / ``down`` / ``status`` / ``history`` / ``rollback``
- ``logs.py``     — ``logs``
"""

from __future__ import annotations

import typer

from src.cli.commands.fly_auth import fly_auth_app
from src.cli.commands.fly_db import fly_db_app

# Define fks_app before importing submodules so their @fks_app.command()
# decorators can resolve it from the partially-initialized package.
fks_app = typer.Typer(
    name="fks",
    help="Fly.io Kubernetes Service (FKS) deployment commands (private beta).",
    no_args_is_help=True,
)

# Register sub-typers before loading submodules.
fks_app.add_typer(fly_auth_app, name="auth")
fks_app.add_typer(fly_db_app, name="db")

# Import submodules after fks_app is defined so their @fks_app.command()
# decorators succeed.
from src.cli.commands.fks import (  # noqa: F401, E402
    clusters,
    deploy,
    logs,
)
