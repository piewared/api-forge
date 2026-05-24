"""Verify that ``fix_all_src_references`` rewrites the placeholder package
prefix inside ``.j2`` template files.

Bug context: prior to this fix, the post-generation rewriter only walked
``*.py``/``*.yml``/``Dockerfile``/``docker-compose*.yml`` — leaving the
Jinja2 templates in ``cli/templates/`` with hard-coded imports rooted at
the placeholder package. After Copier renames the package, any
``api-forge-cli entity add`` in the generated project would emit files
with broken imports.

The fix is one line in ``scripts/post_gen_setup.py``: include ``*.j2`` in
the pattern list. These tests guard against the rewriter regressing on
that.

Implementation note — this file deliberately avoids writing the literal
``from <placeholder>.`` or ``"<placeholder>.app`` substrings anywhere:
``fix_all_src_references`` itself runs over ``*.py`` at post-gen time,
so any literal placeholder-prefixed reference here would be rewritten
to ``<user-package>.`` in the generated project — silently invalidating
every fixture and assertion. We build those substrings from ``_S`` plus
``+`` concatenation so the rewriter's contiguous-text regexes never
match in this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make scripts/ importable (mirrors how the post-gen script runs).
_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from post_gen_setup import fix_all_src_references  # noqa: E402

# Placeholder package name — split out so this test file's literal text
# never contains the contiguous ``src.`` substring the rewriter looks for.
_S = "src"


class TestJ2Rewrite:
    def test_rewrites_from_src_imports_in_j2(self, tmp_path: Path) -> None:
        """A placeholder-prefixed ``from`` import inside a ``.j2`` template is
        rewritten to use the new package name."""
        j2 = tmp_path / "templates" / "entity.py.j2"
        j2.parent.mkdir(parents=True)
        j2.write_text(
            "from " + _S + ".app.entities.core._base import Entity\n"
            "\n"
            "class {{entity_name}}(Entity):\n"
            "    pass\n"
        )

        fix_all_src_references(tmp_path, "mypkg")

        result = j2.read_text()
        assert "from mypkg.app.entities.core._base import Entity" in result
        assert ("from " + _S + ".app") not in result

    def test_preserves_jinja_escape_syntax(self, tmp_path: Path) -> None:
        """Jinja escape constructs like ``{{ "{" }}`` must survive the
        regex-based rewrite untouched."""
        j2 = tmp_path / "templates" / "router.py.j2"
        j2.parent.mkdir(parents=True)
        j2.write_text(
            "from " + _S + ".app.api.http.deps import get_db_session\n"
            "\n"
            '@router.get("/{{ "{" }}item_id{{ "}" }}")\n'
            "def get_item(item_id: str):\n"
            '    return {{ "{" }}"id": item_id{{ "}" }}\n'
        )

        fix_all_src_references(tmp_path, "mypkg")

        result = j2.read_text()
        assert "from mypkg.app.api.http.deps import get_db_session" in result
        # Jinja escape syntax must be untouched.
        assert '{{ "{" }}item_id{{ "}" }}' in result
        assert '{{ "{" }}"id": item_id{{ "}" }}' in result

    def test_rewrites_quoted_string_module_paths_in_j2(self, tmp_path: Path) -> None:
        """Quoted-string module paths (used in YAML command arrays and
        string literals) are also rewritten."""
        j2 = tmp_path / "templates" / "worker.j2"
        j2.parent.mkdir(parents=True)
        j2.write_text('command: ["python", "-m", "' + _S + '.app.worker.example"]\n')

        fix_all_src_references(tmp_path, "mypkg")

        assert 'command: ["python", "-m", "mypkg.app.worker.example"]' in j2.read_text()
