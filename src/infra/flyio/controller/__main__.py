"""Generate FlyCtlControllerSync stub file.

Usage:
    python -m src.infra.flyio.controller
"""

from pathlib import Path

from ._stubs import generate_sync_stubs

stub_content = generate_sync_stubs()

stub_path = Path(__file__).parent / "__init__.pyi"
stub_path.write_text(stub_content)

print(f"Generated type stubs: {stub_path}")
print(f"{len(stub_content.splitlines())} lines")
