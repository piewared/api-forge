"""Backwards-compatible re-export of ``run_sync``.

The canonical location is now :mod:`src.utils.run_sync` so that the
``infra.flyio`` package can use it without depending on ``infra.k8s``
(which gets excluded when the template is generated with
``include_k8s_deploy=false``). This shim is preserved so existing call
sites continue to work; new code should import from ``src.utils.run_sync``.
"""

from src.utils.run_sync import run_sync

__all__ = ["run_sync"]
