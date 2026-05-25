"""End-to-end tests for the deployment-target toggle combinations.

Runs ``copier copy`` against the template with each of the four likely
combinations of ``include_fly_deploy`` × ``include_k8s_deploy`` and asserts:

  * Excluded directories really are absent from the generated project.
  * ``pyproject.toml`` doesn't carry deps that are only used by excluded
    code paths.
  * Generated central CLI bootstrap files (``cli/__init__.py``,
    ``cli/commands/__init__.py``, ``cli/context.py``, ``cli/commands/db/__init__.py``)
    have rendered correctly — no leftover Jinja syntax, the right
    subcommands imported, and so on.

These tests are deliberately heavy (each ``copier copy`` takes a few
seconds) but they're the only way to catch toggle-driven drift before
users do.

In addition, the slow ``TestCliImportsSucceed`` class below runs
``uv sync && uv run api-forge-cli --help`` against each generated
project. That catches *import-time* bugs the static checks can't see —
e.g. a stale ``from .runtime_fly`` left behind in a .jinja file, or a
module-level ``import psycopg2`` that breaks the slimmest combo. Marked
``slow`` so a normal ``pytest -m "not slow"`` run skips it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# The template root is two parents up from this test file (tests/e2e/template/).
TEMPLATE_DIR = Path(__file__).resolve().parents[3]


def _run_copier(dest: Path, *, include_fly: bool, include_k8s: bool) -> None:
    """Invoke ``copier copy`` with the given toggle answers."""
    cmd = [
        sys.executable,
        "-m",
        "copier",
        "copy",
        "--force",
        "--trust",
        "--vcs-ref",
        "HEAD",
        "--data",
        "project_name=Toggle Test",
        "--data",
        "project_slug=toggle_test",
        "--data",
        "package_name=toggle_test",
        "--data",
        f"include_fly_deploy={'true' if include_fly else 'false'}",
        "--data",
        f"include_k8s_deploy={'true' if include_k8s else 'false'}",
        # Disable copier-update tracking; we don't need a git VCS source
        "--data-file",
        "/dev/null",
        str(TEMPLATE_DIR),
        str(dest),
    ]
    # Some copier versions don't accept --data-file=/dev/null cleanly; drop
    # those args and let copier complain only on real failures.
    cmd = [arg for arg in cmd if arg not in ("--data-file", "/dev/null")]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        pytest.fail(
            f"copier copy failed (exit {result.returncode})\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Fixtures: one tmp project per toggle combination.
# scope='module' so each combination runs copier once per pytest session.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def project_minimal(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """include_fly_deploy=false, include_k8s_deploy=false — slimmest project."""
    dest = tmp_path_factory.mktemp("toggle_minimal")
    shutil.rmtree(dest)
    _run_copier(dest, include_fly=False, include_k8s=False)
    return dest


@pytest.fixture(scope="module")
def project_fly_only(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """include_fly_deploy=true, include_k8s_deploy=false — Fly-only deploys."""
    dest = tmp_path_factory.mktemp("toggle_fly")
    shutil.rmtree(dest)
    _run_copier(dest, include_fly=True, include_k8s=False)
    return dest


@pytest.fixture(scope="module")
def project_k8s_only(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """include_fly_deploy=false, include_k8s_deploy=true — K8s-only deploys."""
    dest = tmp_path_factory.mktemp("toggle_k8s")
    shutil.rmtree(dest)
    _run_copier(dest, include_fly=False, include_k8s=True)
    return dest


@pytest.fixture(scope="module")
def project_kitchen_sink(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """include_fly_deploy=true, include_k8s_deploy=true — both targets."""
    dest = tmp_path_factory.mktemp("toggle_both")
    shutil.rmtree(dest)
    _run_copier(dest, include_fly=True, include_k8s=True)
    return dest


# ---------------------------------------------------------------------------
# Path helpers — paths are relative to the generated project's package dir.
# ---------------------------------------------------------------------------

# Fly-only paths that should be absent when include_fly_deploy=false.
# Post-refactor: every fly file lives under one of these directories.
_FLY_ONLY_PATHS = (
    "{pkg}/cli/commands/fly",
    "{pkg}/cli/commands/fly_db",
    "{pkg}/infra/flyio",
)

# K8s-only paths that should be absent when include_k8s_deploy=false.
# Post-refactor: every k8s file lives under one of these directories.
_K8S_ONLY_PATHS = (
    "{pkg}/cli/commands/k8s",
    "{pkg}/cli/deployment/helm_deployer",
    "{pkg}/infra/k8s",
)

PKG = "toggle_test"


def _expand(paths: tuple[str, ...]) -> list[str]:
    return [p.format(pkg=PKG) for p in paths]


# ---------------------------------------------------------------------------
# Tests: minimal (no fly, no k8s)
# ---------------------------------------------------------------------------


class TestMinimal:
    """The slim default: no fly, no k8s. ~5–6k LOC of FastAPI app + dev tooling."""

    def test_fly_subtree_absent(self, project_minimal: Path) -> None:
        for rel in _expand(_FLY_ONLY_PATHS):
            assert not (project_minimal / rel).exists(), (
                f"{rel} should be excluded but is present"
            )

    def test_k8s_subtree_absent(self, project_minimal: Path) -> None:
        for rel in _expand(_K8S_ONLY_PATHS):
            assert not (project_minimal / rel).exists(), (
                f"{rel} should be excluded but is present"
            )

    def test_cli_init_does_not_import_fly_or_k8s(self, project_minimal: Path) -> None:
        cli_init = project_minimal / PKG / "cli" / "__init__.py"
        assert cli_init.exists()
        content = cli_init.read_text()
        assert "fly_app" not in content
        assert "k8s_app" not in content
        assert "{%" not in content, "Jinja syntax leaked into rendered file"

    def test_pyproject_no_k8s_deps(self, project_minimal: Path) -> None:
        content = (project_minimal / "pyproject.toml").read_text()
        assert "kr8s" not in content
        assert "ruamel.yaml" not in content

    def test_app_subtree_intact(self, project_minimal: Path) -> None:
        """FastAPI app code must still be present — toggles only affect deploy targets."""
        app_dir = project_minimal / PKG / "app"
        assert (app_dir / "api" / "http" / "app.py").exists()
        assert (app_dir / "entities" / "core" / "user").is_dir()


# ---------------------------------------------------------------------------
# Tests: fly-only
# ---------------------------------------------------------------------------


class TestFlyOnly:
    def test_fly_subtree_present(self, project_fly_only: Path) -> None:
        for rel in _expand(_FLY_ONLY_PATHS):
            assert (project_fly_only / rel).exists(), f"{rel} should be present"

    def test_k8s_subtree_absent(self, project_fly_only: Path) -> None:
        for rel in _expand(_K8S_ONLY_PATHS):
            assert not (project_fly_only / rel).exists(), (
                f"{rel} should be excluded but is present"
            )

    def test_cli_init_imports_fly_not_k8s(self, project_fly_only: Path) -> None:
        content = (project_fly_only / PKG / "cli" / "__init__.py").read_text()
        assert "fly_app" in content
        assert "k8s_app" not in content
        assert "{%" not in content

    def test_pyproject_no_k8s_deps(self, project_fly_only: Path) -> None:
        content = (project_fly_only / "pyproject.toml").read_text()
        assert "kr8s" not in content
        assert "ruamel.yaml" not in content


# ---------------------------------------------------------------------------
# Tests: k8s-only
# ---------------------------------------------------------------------------


class TestK8sOnly:
    def test_k8s_subtree_present(self, project_k8s_only: Path) -> None:
        for rel in _expand(_K8S_ONLY_PATHS):
            assert (project_k8s_only / rel).exists(), f"{rel} should be present"

    def test_fly_subtree_absent(self, project_k8s_only: Path) -> None:
        for rel in _expand(_FLY_ONLY_PATHS):
            assert not (project_k8s_only / rel).exists(), (
                f"{rel} should be excluded but is present"
            )

    def test_cli_init_imports_k8s_not_fly(self, project_k8s_only: Path) -> None:
        content = (project_k8s_only / PKG / "cli" / "__init__.py").read_text()
        assert "k8s_app" in content
        assert "fly_app" not in content
        assert "{%" not in content

    def test_pyproject_keeps_k8s_deps(self, project_k8s_only: Path) -> None:
        content = (project_k8s_only / "pyproject.toml").read_text()
        assert "kr8s" in content
        assert "ruamel.yaml" in content

    def test_context_includes_k8s_controller(self, project_k8s_only: Path) -> None:
        content = (project_k8s_only / PKG / "cli" / "context.py").read_text()
        assert "k8s_controller" in content
        assert "{%" not in content


# ---------------------------------------------------------------------------
# Tests: kitchen sink
# ---------------------------------------------------------------------------


class TestKitchenSink:
    def test_both_subtrees_present(self, project_kitchen_sink: Path) -> None:
        for rel in _expand(_FLY_ONLY_PATHS) + _expand(_K8S_ONLY_PATHS):
            assert (project_kitchen_sink / rel).exists(), f"{rel} should be present"

    def test_cli_init_imports_both(self, project_kitchen_sink: Path) -> None:
        content = (project_kitchen_sink / PKG / "cli" / "__init__.py").read_text()
        assert "fly_app" in content
        assert "k8s_app" in content
        assert "{%" not in content

    def test_pyproject_keeps_k8s_deps(self, project_kitchen_sink: Path) -> None:
        content = (project_kitchen_sink / "pyproject.toml").read_text()
        assert "kr8s" in content
        assert "ruamel.yaml" in content


# ---------------------------------------------------------------------------
# Cross-cutting: FKS is dead, no combination should resurrect it.
# ---------------------------------------------------------------------------


class TestPostgresDefault:
    """``use_postgres`` defaults to false. The four toggle fixtures above
    don't override it, so all generated projects should default to SQLite
    and have ``psycopg2-binary`` stripped.
    """

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "project_minimal",
            "project_fly_only",
            "project_k8s_only",
            "project_kitchen_sink",
        ],
    )
    def test_psycopg2_binary_absent(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        project = request.getfixturevalue(fixture_name)
        content = (project / "pyproject.toml").read_text()
        assert '"psycopg2-binary' not in content, (
            "psycopg2-binary should be stripped when use_postgres=false"
        )

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "project_minimal",
            "project_fly_only",
            "project_k8s_only",
            "project_kitchen_sink",
        ],
    )
    def test_database_url_default_is_sqlite(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        project = request.getfixturevalue(fixture_name)
        content = (project / "config.yaml").read_text()
        assert "DATABASE_URL:-sqlite:///" in content, (
            "config.yaml should default DATABASE_URL to a SQLite URL when "
            "use_postgres=false"
        )
        assert "DATABASE_URL:-postgresql" not in content, (
            "Stale postgres default still present in config.yaml"
        )


class TestNoFKS:
    @pytest.mark.parametrize(
        "fixture_name",
        [
            "project_minimal",
            "project_fly_only",
            "project_k8s_only",
            "project_kitchen_sink",
        ],
    )
    def test_fks_artefacts_absent(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        project = request.getfixturevalue(fixture_name)
        # Source-level fks artefacts should never appear in any combination.
        assert not (project / PKG / "cli" / "commands" / "fks").exists()
        assert not (
            project / PKG / "infra" / "flyio" / "controller" / "fks.py"
        ).exists()

        # No fks references in env example or config.yaml.
        env = (
            (project / ".env.example").read_text()
            if (project / ".env.example").exists()
            else ""
        )
        cfg = (
            (project / "config.yaml").read_text()
            if (project / "config.yaml").exists()
            else ""
        )
        assert "FKS" not in env
        assert "fks" not in cfg


# ---------------------------------------------------------------------------
# Cross-cutting: post-gen rewriter must be idempotent on generated output.
#
# After ``copier copy`` + the ``_tasks`` hook, no ``src.<top-level>``
# substring should remain anywhere in the generated tree — the rewriter
# already swapped them all for ``<package_name>.<top-level>``. Running it
# again with a different target name must therefore touch zero files.
#
# This catches the bug class behind issue D: a test fixture (or any file)
# whose source contains literal ``from src.app`` / ``"src.cli`` substrings
# that the *first* rewriter pass at post-gen rewrites — silently
# invalidating the fixture's own assertions. Re-running here surfaces any
# residual placeholder-prefixed substring as a non-zero ``fixed`` count.
# ---------------------------------------------------------------------------


class TestRewriterIdempotency:
    """``rewrite_package_references`` must be a no-op on a generated project."""

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "project_minimal",
            "project_fly_only",
            "project_k8s_only",
            "project_kitchen_sink",
        ],
    )
    def test_rewriter_is_noop_on_generated_project(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        """If any file in the generated project still carries a
        ``src.<top-level>`` substring after generation, ``fixed`` will be
        non-zero and the failing-file list will pinpoint the regression."""
        # Import lazily so this test file imports cleanly even if the
        # template's scripts/ dir layout changes.
        import sys

        scripts_dir = TEMPLATE_DIR / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from rename_helpers import rewrite_package_references  # noqa: PLC0415

        project = request.getfixturevalue(fixture_name)

        # Use a clearly-bogus target so any rewrite is obviously a bug, not a
        # collision with the real package name.
        fixed = rewrite_package_references(
            project, frm="src", to="__SENTINEL_DO_NOT_MERGE__", verbose=False
        )
        assert fixed == 0, (
            f"{fixed} file(s) in {fixture_name} still contained placeholder-"
            f"prefixed substrings after generation — the post-gen rewriter "
            f"missed them on the first pass, or a test fixture's own source "
            f"contains literal placeholder substrings that the rewriter "
            f"silently mangles. Inspect with: "
            f"`git -C {project} diff` to see which files changed."
        )


# ---------------------------------------------------------------------------
# Import-time verification (slow)
#
# Static file-presence checks (above) catch toggle drift in the file layout
# but they can't see import-time bugs in rendered code: a stale
# `from .runtime_fly import ...` left in a .jinja, an unconditional
# `import psycopg2` at module top, etc. Those slip through until a real user
# runs `uv sync && api-forge-cli ...` — which is exactly the bug class that
# triggered adding this section.
#
# Each `uv sync` is 30-90s, so the whole class is gated by `@pytest.mark.slow`
# and pinned to a single xdist worker via `xdist_group` so the four projects
# only get synced once each (module-scoped fixture).
# ---------------------------------------------------------------------------


def _uv_sync(project: Path) -> None:
    """Run `uv sync` inside a generated project. Fails the test on non-zero exit."""
    result = subprocess.run(
        ["uv", "sync", "--quiet"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        pytest.fail(
            f"uv sync failed in {project} (exit {result.returncode})\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def _run_cli(project: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a CLI command via `uv run` inside a generated project, no stdin."""
    return subprocess.run(
        ["uv", "run", *args],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )


def _assert_no_import_failure(
    result: subprocess.CompletedProcess[str], context: str
) -> None:
    """Fail loudly on tracebacks or import errors — the bug class we care about."""
    assert result.returncode == 0, (
        f"{context} exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    for marker in ("Traceback", "ModuleNotFoundError", "ImportError"):
        assert marker not in result.stderr, (
            f"{marker} surfaced from {context}:\n{result.stderr}"
        )


@pytest.fixture(scope="module")
def synced_minimal(project_minimal: Path) -> Path:
    _uv_sync(project_minimal)
    return project_minimal


@pytest.fixture(scope="module")
def synced_fly_only(project_fly_only: Path) -> Path:
    _uv_sync(project_fly_only)
    return project_fly_only


@pytest.fixture(scope="module")
def synced_k8s_only(project_k8s_only: Path) -> Path:
    _uv_sync(project_k8s_only)
    return project_k8s_only


@pytest.fixture(scope="module")
def synced_kitchen_sink(project_kitchen_sink: Path) -> Path:
    _uv_sync(project_kitchen_sink)
    return project_kitchen_sink


@pytest.mark.slow
@pytest.mark.serial
@pytest.mark.xdist_group("template_e2e_sync")
class TestCliImportsSucceed:
    """`uv sync && api-forge-cli ...` must succeed in every toggle combination.

    This is the only check that exercises the rendered code's import graph
    end-to-end. It exists because file-presence checks let a real bug ship —
    `ModuleNotFoundError: ... runtime_fly` in a freshly generated project.
    """

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "synced_minimal",
            "synced_fly_only",
            "synced_k8s_only",
            "synced_kitchen_sink",
        ],
    )
    def test_help_runs_cleanly(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        project = request.getfixturevalue(fixture_name)
        result = _run_cli(project, ["api-forge-cli", "--help"])
        _assert_no_import_failure(result, f"`api-forge-cli --help` ({fixture_name})")

    def test_secrets_generate_pki_runs_in_minimal(self, synced_minimal: Path) -> None:
        """Regression test for the exact command that surfaced the original bug.

        `secrets generate --pki` in the slimmest combo hits the most stripped-down
        import path — no fly, no k8s, no postgres. If any optional dep leaks
        into the CLI's import graph, this command catches it.
        """
        result = _run_cli(
            synced_minimal, ["api-forge-cli", "secrets", "generate", "--pki"]
        )
        _assert_no_import_failure(result, "`secrets generate --pki` (minimal)")
