"""PostgreSQL database management for Fly.io deployments.

This package provides db subcommands under 'fly' for managing PostgreSQL
databases on Fly.io, supporting both Fly Managed Postgres (MPG) and
legacy Fly Postgres.

Subcommands:
- create managed/unmanaged: Provision new Postgres clusters
- list-dbs, attach, connect, destroy: Cluster management
- init, verify, sync, backup, reset, migrate: Database workflow operations
"""

import typer

# create_app lives in create.py — no cycle because create.py doesn't import from __init__
from src.cli.commands.fly_db.create import create_app  # noqa: E402

fly_db_app = typer.Typer(
    name="db",
    help="PostgreSQL database management for Fly.io.",
    no_args_is_help=True,
)
fly_db_app.add_typer(create_app, name="create")

# Import after fly_db_app is defined so workflows/manage can use it as a decorator
from src.cli.commands.fly_db import manage, workflows  # noqa: F401, E402
