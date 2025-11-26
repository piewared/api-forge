"""Utilities for package path detection."""

from pathlib import Path


def get_package_root() -> Path:
    """Get the absolute path to the package root directory.

    Returns the directory containing the app/ module, which is the package root.
    This works both in infrastructure development (src/) and generated projects (any name).

    Returns:
        Path: Absolute path to the package root directory
    """
    # Start from this file's location
    current_file = Path(__file__).resolve()

    # This file is in {package}/utils/package_utils.py
    # So package root is 2 levels up
    package_root = current_file.parent.parent

    # Verify it's the correct directory by checking for app/
    if not (package_root / "app").exists():
        raise RuntimeError(
            f"Could not find package root. Expected app/ directory in {package_root}"
        )

    return package_root


def get_package_name() -> str:
    """Get the name of the current package.

    Returns the directory name of the package root.
    Works for both 'src' (infrastructure) and custom package names (generated projects).

    Returns:
        str: Package name (e.g., 'src', 'my_api_project', etc.)
    """
    return get_package_root().name


def get_package_module_path() -> str:
    """Get the Python module path for the package.

    Returns:
        str: Module path (e.g., 'src', 'my_api_project')
    """
    return get_package_name()
