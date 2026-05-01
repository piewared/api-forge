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

These tests do NOT run ``uv sync`` or actually exercise the generated
CLI — that's an order of magnitude more expensive and is covered by
``test_copier_to_deployment.py``. We just verify the static project
structure is consistent with the toggles.
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
