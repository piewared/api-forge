"""Verify that ``fix_all_src_references`` rewrites ``src.`` references inside
``.j2`` template files.

Bug context: prior to this fix, the post-generation rewriter only walked
``*.py``/``*.yml``/``Dockerfile``/``docker-compose*.yml`` — leaving the
Jinja2 templates in ``cli/templates/`` with hard-coded ``from src.app...``
imports. After Copier renames the package, any ``api-forge-cli entity add``
in the generated project would emit files with broken imports.

The fix is one line in ``scripts/post_gen_setup.py``: include ``*.j2`` in the
pattern list. These tests guard against the rewriter regressing on that.
"""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

# Make scripts/ importable (mirrors how the post-gen script runs).
_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from post_gen_setup import fix_all_src_references  # noqa: E402


class TestJ2Rewrite:
    def test_rewrites_from_src_imports_in_j2(self, tmp_path: Path) -> None:
        """``from src.app...`` inside a ``.j2`` template is rewritten to use
        the new package name."""
        j2 = tmp_path / "templates" / "entity.py.j2"
        j2.parent.mkdir(parents=True)
        j2.write_text(
            dedent(
                """\
                from src.app.entities.core._base import Entity

                class {{entity_name}}(Entity):
                    pass
                """
            )
        )

        fix_all_src_references(tmp_path, "mypkg")

        result = j2.read_text()
        assert "from mypkg.app.entities.core._base import Entity" in result
        assert "from src.app" not in result

    def test_preserves_jinja_escape_syntax(self, tmp_path: Path) -> None:
        """Jinja escape constructs like ``{{ "{" }}`` must survive the
        regex-based rewrite untouched."""
        j2 = tmp_path / "templates" / "router.py.j2"
        j2.parent.mkdir(parents=True)
        j2.write_text(
            dedent(
                """\
                from src.app.api.http.deps import get_db_session

                @router.get("/{{ "{" }}item_id{{ "}" }}")
                def get_item(item_id: str):
                    return {{ "{" }}"id": item_id{{ "}" }}
                """
            )
        )

        fix_all_src_references(tmp_path, "mypkg")

        result = j2.read_text()
        assert "from mypkg.app.api.http.deps import get_db_session" in result
        # Jinja escape syntax must be untouched.
        assert '{{ "{" }}item_id{{ "}" }}' in result
        assert '{{ "{" }}"id": item_id{{ "}" }}' in result

    def test_rewrites_quoted_string_module_paths_in_j2(self, tmp_path: Path) -> None:
        """Quoted-string module paths like ``"src.app.worker.foo"`` are also
        rewritten (used in YAML command arrays and string literals)."""
        j2 = tmp_path / "templates" / "worker.j2"
        j2.parent.mkdir(parents=True)
        j2.write_text('command: ["python", "-m", "src.app.worker.example"]\n')

        fix_all_src_references(tmp_path, "mypkg")

        assert 'command: ["python", "-m", "mypkg.app.worker.example"]' in j2.read_text()
