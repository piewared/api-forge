from pathlib import Path


def make_postgres_url(
    user: str, password: str, host: str, port: int, dbname: str
) -> str:
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def get_project_root() -> Path:
    """Get the project root directory.

    Walks up from the module location to find the project root,
    identified by the presence of pyproject.toml.

    Returns:
        Path to the project root directory
    """
    current = Path(__file__).resolve()

    # Walk up the directory tree looking for pyproject.toml
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists():
            return parent

    # Fallback to four levels up (src/cli/commands/shared.py -> project root)
    return Path(__file__).parent.parent.parent.parent


def get_package_root() -> Path:
    """Return the directory containing the Python package source.

    Why: post-gen copier renames ``src/`` → ``<package_name>/``. Hardcoded
    ``get_project_root() / "src"`` paths break in generated projects because
    the bare-string ``"src"`` segment is invisible to the post-gen
    ``src.`` → ``<pkg>.`` rewriter. Resolving from ``__file__`` survives
    the rename: this module lives at ``<root>/utils/paths.py`` in both
    the source template and any generated project.
    """
    return Path(__file__).resolve().parent.parent
