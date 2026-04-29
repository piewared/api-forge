"""Stub file generator for the Fly.io controller package.

Not part of the public API — invoked only by ``__main__.py``.
"""

from __future__ import annotations


def generate_sync_stubs() -> str:
    """Generate a .pyi stub file using AST parsing.

    Returns:
        The complete content of the .pyi stub file as a string
    """
    import ast
    import inspect
    from pathlib import Path

    from ._controller import FlyCtlController

    # Read and parse all mixin source files + this file for dataclasses
    source_dir = Path(__file__).parent

    # Extract dataclasses from types.py
    types_source = (source_dir / "types.py").read_text()
    types_tree = ast.parse(types_source)

    dataclass_defs = []
    dataclass_names = []
    for node in ast.walk(types_tree):
        if isinstance(node, ast.ClassDef):
            has_dataclass_decorator = any(
                (isinstance(d, ast.Name) and d.id == "dataclass")
                or (isinstance(d, ast.Attribute) and d.attr == "dataclass")
                for d in node.decorator_list
            )
            if has_dataclass_decorator:
                dataclass_names.append(node.name)
                fields = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(
                        item.target, ast.Name
                    ):
                        field_name = item.target.id
                        annotation = ast.unparse(item.annotation)
                        if item.value:
                            default = ast.unparse(item.value)
                            fields.append(f"    {field_name}: {annotation} = {default}")
                        else:
                            fields.append(f"    {field_name}: {annotation}")

                docstring = ""
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                ):
                    docstring_value = node.body[0].value.value
                    if isinstance(docstring_value, bytes):
                        docstring_value = docstring_value.decode("utf-8")
                    docstring = f'    """{docstring_value}"""'

                dataclass_def = f"@dataclass\nclass {node.name}:\n"
                if docstring:
                    dataclass_def += f"{docstring}\n"
                dataclass_def += "\n".join(fields) if fields else "    pass"
                dataclass_defs.append(dataclass_def + "\n")

    # Get methods from composed FlyCtlController using inspect
    methods = []
    async_methods = []
    for name, method in inspect.getmembers(
        FlyCtlController, predicate=inspect.isfunction
    ):
        if name.startswith("_"):
            continue

        sig = inspect.signature(method)
        params = []
        seen_keyword_only_separator = False

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            if (
                param.kind == inspect.Parameter.KEYWORD_ONLY
                and not seen_keyword_only_separator
            ):
                params.append("*")
                seen_keyword_only_separator = True

            param_str = param_name
            if param.annotation != inspect.Parameter.empty:
                annotation = param.annotation
                if isinstance(annotation, type):
                    annotation = annotation.__name__
                else:
                    annotation = str(annotation).replace("typing.", "")
                param_str += f": {annotation}"

            if param.default != inspect.Parameter.empty:
                if param.default is None:
                    param_str += " = None"
                elif isinstance(param.default, str):
                    param_str += f' = "{param.default}"'
                elif isinstance(param.default, bool):
                    param_str += f" = {param.default}"
                else:
                    param_str += f" = {param.default}"

            params.append(param_str)

        params_str = ", ".join(params)

        return_annotation = sig.return_annotation
        if return_annotation == inspect.Signature.empty:
            sync_return_type = "Any"
            async_return_type = "Any"
        else:
            return_type_str = str(return_annotation).replace("typing.", "")
            # inspect.signature() on `async def foo() -> T` returns T directly,
            # not Coroutine[Any, Any, T], so both wrappers share the same type.
            sync_return_type = return_type_str
            async_return_type = return_type_str

        methods.append(f"    def {name}(self, {params_str}) -> {sync_return_type}: ...")
        async_methods.append(
            f"    async def {name}(self, {params_str}) -> {async_return_type}: ..."
        )

    all_exports = dataclass_names + ["FlyCtlController", "FlyCtlControllerSync"]

    stub_content = f'''"""Type stubs for Fly.io controller package.

This file is AUTO-GENERATED by running:
    python -m src.infra.flyio.controller

Do not edit manually. Regenerate after updating FlyCtlController.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = {all_exports!r}


# =============================================================================
# Data Types (AUTO-EXTRACTED)
# =============================================================================

{chr(10).join(dataclass_defs)}


# =============================================================================
# Async Controller
# =============================================================================

class FlyCtlController:
    """Controller for Fly.io operations via flyctl CLI."""

{chr(10).join(async_methods)}


# =============================================================================
# Synchronous Wrapper
# =============================================================================

class FlyCtlControllerSync:
    """Synchronous wrapper for FlyCtlController with full type hints."""

    _controller: FlyCtlController

    def __init__(self, controller: FlyCtlController | None = None) -> None: ...

{chr(10).join(methods)}
'''

    return stub_content
