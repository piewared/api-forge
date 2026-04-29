"""Quick-iteration entry point for fly commands."""

import os
import sys

from . import fly_app

if len(sys.argv) == 1:
    # No CLI args — build from env vars for quick iteration.
    svc = os.environ.get("FLY_TEST_SERVICE", "app")
    extra: list[str] = ["up", "--service", svc]
    if region_override := os.environ.get("FLY_TEST_REGION"):
        extra += ["--region", region_override]
    if os.environ.get("FLY_SKIP_DB_CHECK") == "1":
        extra.append("--skip-db-check")
    sys.argv = [sys.argv[0]] + extra

fly_app()
