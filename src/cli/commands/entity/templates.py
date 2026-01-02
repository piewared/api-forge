"""Jinja2 templates for entity scaffolding."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from src.utils.paths import get_project_root


def get_template_env() -> Environment:
    """Get Jinja2 environment for template rendering."""
    template_dir = get_project_root() / "src" / "cli" / "templates"
    return Environment(loader=FileSystemLoader(Path(template_dir)))


def render_template_to_file(
    template_name: str, output_path: Path, context: dict[str, Any]
) -> None:
    """Render a Jinja2 template to a file."""
    env = get_template_env()
    template = env.get_template(template_name)
    content = template.render(**context)
    output_path.write_text(content)
