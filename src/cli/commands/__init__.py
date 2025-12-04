"""CLI command modules organized by deployment target.

This package provides the restructured CLI with separate command groups
for each deployment target (dev, prod, k8s, fly) and utilities (entity, secrets, users).

Command Groups:
- dev: Development environment using Docker Compose
- prod: Production Docker Compose deployment
- k8s: Kubernetes deployment using Helm
- fly: Fly.io Kubernetes (FKS) deployment (future)
- entity: Entity/model scaffolding
- secrets: Secret management utilities
- users: Keycloak user management (dev environment)
"""

from .dev import app as dev_app
from .entity import entity_app
from .fly import fly_app
from .k8s import k8s_app
from .prod import prod_app
from .secrets import secrets_app
from .users import users_app

__all__ = [
    "dev_app",
    "prod_app",
    "k8s_app",
    "fly_app",
    "entity_app",
    "secrets_app",
    "users_app",
]
