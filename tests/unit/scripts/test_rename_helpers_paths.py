"""Verify the rename rewriter covers *path* references, not just module ones.

Bug context: the rewriter handled dotted module references (``from <pkg>.x``)
and container paths with a trailing slash (``/app/<pkg>/``), but not:

- the *host* side of Compose bind mounts (``./<pkg>``, ``../../../<pkg>``), or
- container paths without a trailing slash (``/app/<pkg>:ro``, ``"/app/<pkg>"``).

In a generated project this left ``- ./src:/app/<pkg>:ro`` on the worker
service: a mount whose host path no longer exists. Docker silently created it
as an empty root-owned ``src/`` directory, the worker crash-looped on
``python -m <pkg>.worker.main``, and the root-owned directory then tripped the
update wrapper's "stray src/" preflight.

Implementation note — like ``test_post_gen_setup_j2_rewrite``, this file never
writes the literal placeholder-prefixed substrings, because the rewriter runs
over ``*.py`` at post-gen time and would rewrite this file's own fixtures in
the generated project. Everything is built from ``_S`` by concatenation.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from rename_helpers import rewrite_package_references  # noqa: E402

# Placeholder package name, kept out of contiguous literals.
_S = "src"
_PKG = "mypkg"


def _compose(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "docker-compose.dev.yml"
    path.write_text(body)
    return path


class TestHostSideBindMounts:
    def test_rewrites_dot_slash_host_path(self, tmp_path: Path) -> None:
        """``./<pkg>:/app/<pkg>:ro`` — both sides must move."""
        compose = _compose(
            tmp_path,
            "    volumes:\n      - ./" + _S + ":/app/" + _S + ":ro\n",
        )

        rewrite_package_references(tmp_path, frm=_S, to=_PKG, verbose=False)

        assert f"- ./{_PKG}:/app/{_PKG}:ro" in compose.read_text()
        assert "./" + _S not in compose.read_text()

    def test_rewrites_nested_host_path(self, tmp_path: Path) -> None:
        compose = _compose(
            tmp_path,
            "    volumes:\n      - ./" + _S + "/dev:/app/" + _S + "/dev\n",
        )

        rewrite_package_references(tmp_path, frm=_S, to=_PKG, verbose=False)

        assert f"- ./{_PKG}/dev:/app/{_PKG}/dev" in compose.read_text()

    def test_rewrites_parent_relative_host_path(self, tmp_path: Path) -> None:
        """Nested compose files reach the package via ``../../../``."""
        nested = tmp_path / "infra" / "docker" / "dev" / "keycloak"
        nested.mkdir(parents=True)
        compose = nested / "docker-compose.yml"
        compose.write_text(
            "    volumes:\n      - ../../../" + _S + "/dev:/app/" + _S + "/dev\n"
        )

        rewrite_package_references(tmp_path, frm=_S, to=_PKG, verbose=False)

        assert f"- ../../../{_PKG}/dev:/app/{_PKG}/dev" in compose.read_text()


class TestContainerPathsWithoutTrailingSlash:
    def test_rewrites_bind_mount_target(self, tmp_path: Path) -> None:
        compose = _compose(tmp_path, "      - ./x:/app/" + _S + ":ro\n")

        rewrite_package_references(tmp_path, frm=_S, to=_PKG, verbose=False)

        assert f":/app/{_PKG}:ro" in compose.read_text()

    def test_rewrites_quoted_sys_path_entry(self, tmp_path: Path) -> None:
        script = tmp_path / "setup_script.py"
        script.write_text('sys.path.insert(0, "/app/' + _S + '")\n')

        rewrite_package_references(tmp_path, frm=_S, to=_PKG, verbose=False)

        assert f'sys.path.insert(0, "/app/{_PKG}")' in script.read_text()

    def test_still_rewrites_paths_with_trailing_slash(self, tmp_path: Path) -> None:
        """The pre-existing behavior must not regress."""
        compose = _compose(
            tmp_path,
            '      test: ["CMD", "python", "/app/' + _S + '/worker/health_check.py"]\n',
        )

        rewrite_package_references(tmp_path, frm=_S, to=_PKG, verbose=False)

        assert f"/app/{_PKG}/worker/health_check.py" in compose.read_text()


class TestSegmentBoundaries:
    """``<pkg>`` must only match a whole path segment."""

    def test_leaves_longer_absolute_segment_alone(self, tmp_path: Path) -> None:
        compose = _compose(tmp_path, "      - /app/" + _S + "ipts:/tmp/x\n")

        rewrite_package_references(tmp_path, frm=_S, to=_PKG, verbose=False)

        assert "/app/" + _S + "ipts" in compose.read_text()

    def test_leaves_longer_relative_segment_alone(self, tmp_path: Path) -> None:
        compose = _compose(tmp_path, "      - ./" + _S + "ipts:/tmp/x\n")

        rewrite_package_references(tmp_path, frm=_S, to=_PKG, verbose=False)

        assert "./" + _S + "ipts" in compose.read_text()

    def test_leaves_unrelated_absolute_paths_alone(self, tmp_path: Path) -> None:
        """Only ``/app/<pkg>`` and explicit relative prefixes are in scope."""
        compose = _compose(tmp_path, "      - /usr/" + _S + ":/tmp/x\n")

        rewrite_package_references(tmp_path, frm=_S, to=_PKG, verbose=False)

        assert "/usr/" + _S in compose.read_text()


class TestRoundTripAndIdempotency:
    _BODY = (
        "    volumes:\n"
        "      - ./" + _S + "/dev:/app/" + _S + "/dev\n"
        "      - ./" + _S + ":/app/" + _S + ":ro\n"
        '    command: ["python", "-m", "' + _S + '.worker.main"]\n'
        '    healthcheck: ["python", "/app/' + _S + '/worker/health_check.py"]\n'
    )

    def test_round_trip_is_lossless(self, tmp_path: Path) -> None:
        """The update wrapper renames <pkg> -> src, runs copier, renames back."""
        compose = _compose(tmp_path, self._BODY)

        rewrite_package_references(tmp_path, frm=_S, to=_PKG, verbose=False)
        rewrite_package_references(tmp_path, frm=_PKG, to=_S, verbose=False)

        assert compose.read_text() == self._BODY

    def test_second_forward_pass_is_a_no_op(self, tmp_path: Path) -> None:
        _compose(tmp_path, self._BODY)

        rewrite_package_references(tmp_path, frm=_S, to=_PKG, verbose=False)
        changed = rewrite_package_references(tmp_path, frm=_S, to=_PKG, verbose=False)

        assert changed == 0
