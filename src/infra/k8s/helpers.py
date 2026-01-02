from __future__ import annotations

import os

from cachetools.func import lru_cache  # type: ignore

from src.infra.constants import DEFAULT_CONSTANTS
from src.infra.k8s.controller import KubernetesController, KubernetesControllerSync


@lru_cache(maxsize=1)
def get_k8s_controller() -> KubernetesController:
    """Get an instance of the KubernetesController.

    Returns:
        An instance of KubernetesController
    """
    from src.infra.k8s.kr8s_controller import Kr8sController

    return Kr8sController()


@lru_cache(maxsize=1)
def get_k8s_controller_sync() -> KubernetesControllerSync:
    """Get a synchronous wrapper for KubernetesController.

    Returns:
        An instance of KubernetesControllerSync wrapping the async controller
    """
    from src.infra.k8s.kr8s_controller import Kr8sController

    controller = Kr8sController()
    return KubernetesControllerSync(controller)


def get_namespace() -> str:
    """Get the Kubernetes namespace from config or default."""
    return os.environ.get("K8S_NAMESPACE", DEFAULT_CONSTANTS.DEFAULT_NAMESPACE)


def get_postgres_label() -> str:
    """Get the PostgreSQL pod label selector."""
    return DEFAULT_CONSTANTS.POSTGRES_POD_LABEL
