"""CLI command modules organized by deployment target.

This package provides the restructured CLI with separate command groups
for each deployment target (dev, prod, k8s, fly) and utilities (entity, secrets, users).

Command Groups:
- dev: Development environment using Docker Compose
- prod: Production Docker Compose deployment (includes 'prod db' subcommands)
- k8s: Kubernetes deployment using Helm (includes 'k8s db' subcommands)
- fly: Fly.io deployment (traditional Fly Machines)
- entity: Entity/model scaffolding
- secrets: Secret management utilities
- users: Keycloak user management (dev environment)
"""

from .activity import activity_app
from .config_validate import config_app
from .dev import app as dev_app
from .entity import entity_app
from .fly import fly_app
from .k8s import k8s_app
from .prod import prod_app
from .secrets import secrets_app
from .update import update_app
from .users import users_app
from .workflow import workflow_app

__all__ = [
    "config_app",
    "dev_app",
    "prod_app",
    "k8s_app",
    "fly_app",
    "entity_app",
    "workflow_app",
    "activity_app",
    "secrets_app",
    "update_app",
    "users_app",
]
