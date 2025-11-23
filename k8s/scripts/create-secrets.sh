#!/bin/bash
# Backwards compatibility shim. Prefer ./apply-secrets.sh going forward.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
>&2 echo "[WARN] create-secrets.sh is deprecated. Use apply-secrets.sh instead."
exec "${SCRIPT_DIR}/apply-secrets.sh" "$@"
