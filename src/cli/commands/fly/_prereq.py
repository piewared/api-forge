"""Shared Fly.io prerequisites and controller access.

Consolidates the duplicated _get_fly_controller, _check_flyctl_installed,
_check_authenticated, and _check_prerequisites that were copy-pasted across
fly/, fly_db/, and fly_auth modules.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import typer

from src.cli.shared.console import console
from src.infra.flyio import FlyCtlControllerSync

# Latest flyctl version this template was validated against. Bump when the
# template is re-tested on a newer flyctl. Acts as the floor for the
# staleness warning when flyctl's own ``~/.fly/state.json`` cache is empty
# (which happens whenever ``FLY_NO_UPDATE_CHECK=1`` has been the only way
# flyctl has been invoked — i.e., almost always when using this CLI).
_RECOMMENDED_FLYCTL_VERSION: tuple[int, int, int] = (0, 4, 43)

# How long to wait between version-staleness warnings. Same warning every
# command would be obnoxious; once per week is enough to stay visible
# without nagging in a tight code-iteration loop.
_VERSION_NAG_INTERVAL_SECONDS = 7 * 24 * 60 * 60

# Marker file holds the mtime of the last warning we showed. Delete it to
# force the warning on the next command.
_NAG_MARKER_PATH = Path.home() / ".cache" / "api-forge-cli" / "last-fly-version-nag"


def get_fly_controller() -> FlyCtlControllerSync:
    """Get Fly.io controller instance."""
    return FlyCtlControllerSync()


def check_flyctl_installed(controller: FlyCtlControllerSync) -> None:
    """Check if flyctl is installed and show error if not."""
    if not controller.is_installed():
        console.error("flyctl CLI is not installed.")
        console.info("Install from: https://fly.io/docs/flyctl/install/")
        console.info("  curl -L https://fly.io/install.sh | sh")
        raise typer.Exit(1)


def check_authenticated(controller: FlyCtlControllerSync) -> None:
    """Check if user is authenticated to Fly.io."""
    if not controller.is_authenticated():
        console.error("Not logged in to Fly.io")
        console.info("Run: api-forge-cli fly auth login")
        raise typer.Exit(1)


def check_prerequisites(controller: FlyCtlControllerSync) -> None:
    """Check that flyctl is installed, the user is authenticated, and that
    the installed flyctl isn't older than the version we validated against.

    The version check is best-effort and time-gated; it never blocks a
    deploy.
    """
    check_flyctl_installed(controller)
    check_authenticated(controller)
    check_flyctl_version()


# ---------------------------------------------------------------------------
# Version-staleness warning
#
# We suppress flyctl's in-process auto-update via ``FLY_NO_UPDATE_CHECK=1``
# (see ``src/infra/flyio/controller/base.py``) so deploys aren't interrupted
# by the auto-installer mid-pipeline. The downside is that users would
# silently drift onto an old flyctl forever, missing fixes and gaining
# version skew with the template's tested-against baseline.
#
# This helper restores visibility — without restoring the disruption — by
# emitting a one-line warning at most once a week when the installed
# flyctl is older than the version this template was validated against.
# ---------------------------------------------------------------------------


def check_flyctl_version() -> None:
    """Best-effort: warn if the installed flyctl is older than the recommended
    version. Silently skips on any I/O / parse failure so a flaky check never
    blocks a deploy.
    """
    if not _should_show_version_warning():
        return

    current = _get_current_flyctl_version()
    if current is None:
        return  # Couldn't determine current version — skip silently.

    # Prefer flyctl's own cache (reflects the actual latest release if a
    # check has fired recently) and fall back to our hardcoded recommendation.
    target = _get_cached_latest_flyctl_version() or _RECOMMENDED_FLYCTL_VERSION
    if current >= target:
        return

    cur_str = ".".join(str(x) for x in current)
    tgt_str = ".".join(str(x) for x in target)
    console.warn(f"flyctl {tgt_str} available (you have {cur_str}).")
    console.print("  Auto-update is suppressed during deploys to keep output clean.")
    console.print("  Update manually:  fly version upgrade")
    console.print()
    _record_version_warning()


def _parse_version(s: str) -> tuple[int, int, int] | None:
    """Parse ``X.Y.Z`` (with optional leading ``v``) into a tuple. ``None`` on
    parse failure. Trailing pre-release suffixes are tolerated.
    """
    s = s.lstrip("vV").strip()
    # Drop pre-release/build metadata like "0.4.43-pre" or "0.4.43+abc".
    for sep in ("-", "+"):
        if sep in s:
            s = s.split(sep, 1)[0]
    parts = s.split(".")
    if len(parts) < 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def _get_current_flyctl_version() -> tuple[int, int, int] | None:
    """Run ``fly version --json`` and parse the version. ``None`` on failure."""
    try:
        result = subprocess.run(
            ["fly", "version", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            # Match what the rest of the CLI does — never trigger auto-update.
            env={**os.environ, "FLY_NO_UPDATE_CHECK": "1"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0 or not result.stdout:
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    # flyctl uses ``Version`` (capitalised) today; tolerate variants.
    raw = data.get("Version") or data.get("version")
    if not isinstance(raw, str):
        return None
    return _parse_version(raw)


def _get_cached_latest_flyctl_version() -> tuple[int, int, int] | None:
    """Read the 'latest known' flyctl version from ``~/.fly/state.json``.

    flyctl writes this file as part of its update-check flow. With
    ``FLY_NO_UPDATE_CHECK=1`` set globally that flow rarely runs, so the
    cache is often empty or stale — callers fall back to the hardcoded
    recommendation in that case.
    """
    state_path = Path.home() / ".fly" / "state.json"
    try:
        data = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    latest = data.get("latest_release_version") or data.get("LatestReleaseVersion")
    if not isinstance(latest, str):
        return None
    return _parse_version(latest)


def _should_show_version_warning() -> bool:
    """True if at least the nag interval has passed since the last warning."""
    try:
        last = _NAG_MARKER_PATH.stat().st_mtime
    except OSError:
        return True
    return (time.time() - last) >= _VERSION_NAG_INTERVAL_SECONDS


def _record_version_warning() -> None:
    """Touch the marker file so the warning is gated for the nag interval."""
    try:
        _NAG_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _NAG_MARKER_PATH.touch()
    except OSError:
        # Cache-write errors should never break a deploy.
        pass
