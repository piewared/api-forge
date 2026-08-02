"""Helpers for moving the application package between ``src/`` and the
user-chosen package name.

The template ships its application code under ``src/`` so the repo is
directly importable for development. At post-generation time, the directory
is renamed to ``<package_name>/`` and every ``from src.<x>`` import (plus a
handful of related references in YAML/Dockerfiles/string literals) is
rewritten to point at the new package.

That rename has to be reversible because ``copier update`` works on the
template's *original* path layout. Before delegating to ``copier update``,
the ``api-forge-cli update`` wrapper runs this same logic in the opposite
direction so Copier sees a tree shaped like a fresh template render and can
apply its three-way merge cleanly. After Copier finishes, the post-gen
``_tasks`` run and rewrite back to ``<package_name>``.

Keeping the regex set in one module ensures the two directions can't drift.
"""

from __future__ import annotations

import re
from pathlib import Path

# Files whose contents reference the package name. Mirrors the historical
# ``fix_all_src_references`` glob list in ``post_gen_setup.py`` — adding a
# new file type here is the only edit needed to handle it in both directions.
_REWRITE_PATTERNS: tuple[str, ...] = (
    "*.py",
    "*.yml",
    "*.yaml",
    "*.j2",
    "Dockerfile",
    "docker-compose*.yml",
)

# Directory names that we always skip when walking for rewrite candidates.
_SKIP_DIRS: frozenset[str] = frozenset(
    {".venv", "__pycache__", ".git", "node_modules", "data"}
)


def _candidate_files(project_dir: Path) -> list[Path]:
    """Collect every file the rewriter should look at."""
    files: list[Path] = []
    for pattern in _REWRITE_PATTERNS:
        if pattern == "Dockerfile":
            dockerfile = project_dir / "Dockerfile"
            if dockerfile.exists():
                files.append(dockerfile)
        elif pattern.startswith("docker-compose"):
            files.extend(project_dir.glob(pattern))
        else:
            files.extend(project_dir.rglob(pattern))

    return files


def rewrite_package_references(
    project_dir: Path, *, frm: str, to: str, verbose: bool = True
) -> int:
    """Rewrite references to package ``frm`` so they point at package ``to``.

    Returns the number of files actually modified. Both directions
    (``src`` → ``<pkg>`` and ``<pkg>`` → ``src``) go through this function;
    callers just swap the arguments.

    Covers:
    - Python imports: ``from <frm>.x`` and ``import <frm>.x``.
    - Dotted module strings inside quotes: ``"<frm>.app.worker.main"``,
      ``'<frm>.cli'`` (limited to the known top-level packages —
      ``app``, ``cli``, ``dev``, ``infra``, ``utils``, ``worker`` — so we
      don't eat unrelated subpackage names users may have). When adding a
      new top-level package under ``src/``, extend this whitelist; the
      generated project's tests will start failing with
      ``ModuleNotFoundError: No module named 'src'`` otherwise.
    - Docker container paths: ``/app/<frm>`` → ``/app/<to>``, whether or not a
      trailing slash follows. ``/app/<frm>:ro`` (a bind-mount target) and
      ``"/app/<frm>"`` (a ``sys.path`` entry) both occur in the template.
    - Relative host paths: ``./<frm>`` and ``../../../<frm>`` → the same
      prefix with ``<to>``. These are the *host* side of Compose bind mounts;
      missing them leaves a mount pointing at a directory that no longer
      exists, which Docker then silently re-creates as an empty root-owned
      tree. Anchored to an explicit ``./``/``../`` prefix so unrelated
      absolute paths (``/usr/<frm>``) are never touched.
    - Docker COPY commands: ``COPY <frm>/ <frm>/`` → ``COPY <to>/ <to>/``.

    Path rules use a ``(?![\\w-])`` boundary so ``<frm>`` only matches a whole
    path segment — ``/app/source`` and ``./srcfoo`` are left alone.
    """
    frm_re = re.escape(frm)
    fixed = 0

    for file_path in _candidate_files(project_dir):
        if any(part in _SKIP_DIRS for part in file_path.parts):
            continue
        try:
            original = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        content = original
        content = re.sub(rf"\bfrom {frm_re}\.", f"from {to}.", content)
        content = re.sub(rf"\bimport {frm_re}\.", f"import {to}.", content)
        content = re.sub(
            rf'"{frm_re}\.(app|cli|dev|infra|utils|worker)',
            rf'"{to}.\1',
            content,
        )
        content = re.sub(
            rf"'{frm_re}\.(app|cli|dev|infra|utils|worker)",
            rf"'{to}.\1",
            content,
        )
        # Container-side absolute paths. The boundary (rather than a required
        # trailing slash) is what catches "/app/<frm>:ro" and '"/app/<frm>"'.
        content = re.sub(rf"/app/{frm_re}(?![\w-])", f"/app/{to}", content)
        # Host-side relative paths in Compose bind mounts.
        content = re.sub(
            rf"((?:\.\./)+|\./){frm_re}(?![\w-])",
            rf"\1{to}",
            content,
        )
        content = re.sub(
            rf"COPY(\s+--chown=\S+)?\s+{frm_re}/\s+{frm_re}/",
            rf"COPY\1 {to}/ {to}/",
            content,
        )

        if content != original:
            file_path.write_text(content)
            fixed += 1

    if verbose and fixed:
        print(f"✅ Rewrote {frm}. → {to}. references in {fixed} file(s)")

    return fixed
