"""Worker entrypoint must fail fast when Temporal is disabled.

Two failure modes are exercised:

1. ``config.temporal.enabled = False`` — the user has the dep installed but
   chose to disable Temporal at runtime. The worker should exit with code 2
   and log a clear message; it must NOT try to connect.
2. ``temporalio`` not installed — the user generated a project with
   ``use_temporal=false`` (so the dep was stripped) but somehow ran the
   worker anyway. The module must still be importable, and ``serve``
   must exit cleanly with the same code instead of throwing
   ``ModuleNotFoundError`` at import time.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
import typer

from src.app.runtime.config.config_data import ConfigData
from src.app.runtime.context import with_context


def _disabled_config() -> ConfigData:
    cfg = ConfigData()
    cfg.temporal.enabled = False
    return cfg


class TestServeWhenTemporalDisabled:
    def test_exits_cleanly_with_temporal_enabled_false(self) -> None:
        """``serve`` should ``typer.Exit(code=2)`` when temporal.enabled is False."""
        from src.worker.main import serve

        with with_context(config_override=_disabled_config()):
            with pytest.raises(typer.Exit) as exc:
                serve(queue=None, drain_timeout=600.0, log_level="INFO")
            assert exc.value.exit_code == 2


class TestModuleImportabilityWithoutTemporalio:
    def test_module_imports_when_temporalio_is_missing(self) -> None:
        """``src.worker.main`` must be importable even when ``temporalio``
        isn't installed. The actual ``temporalio`` imports happen lazily
        inside ``serve`` after the enabled-gate.
        """
        for mod in list(sys.modules):
            if mod.startswith("src.worker.main"):
                del sys.modules[mod]

        # ``temporalio: None`` in sys.modules makes ``import temporalio``
        # raise ImportError. Importing src.worker.main should still
        # succeed because all temporalio touches are deferred.
        with patch.dict(sys.modules, {"temporalio": None}):
            try:
                import src.worker.main  # noqa: F401
            except ImportError as exc:
                pytest.fail(
                    f"src.worker.main should import without temporalio "
                    f"installed; got: {exc}"
                )

    def test_serve_exits_cleanly_when_temporalio_is_missing(self) -> None:
        """When ``serve`` runs and the deferred ``import temporalio`` fails,
        we should exit with code 2 and a clear message — not crash with
        ``ModuleNotFoundError``.
        """
        from src.worker.main import serve

        cfg = ConfigData()
        cfg.temporal.enabled = True

        original_import = (
            __builtins__["__import__"]
            if isinstance(__builtins__, dict)
            else __builtins__.__import__
        )

        def _fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("temporalio"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with with_context(config_override=cfg):
            with patch("builtins.__import__", side_effect=_fake_import):
                with pytest.raises(typer.Exit) as exc:
                    serve(queue=None, drain_timeout=600.0, log_level="INFO")
                assert exc.value.exit_code == 2
