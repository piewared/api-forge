
import os
import re
from collections.abc import Iterable
from pathlib import Path

from loguru import logger

_SECRETS_LOADED = False



def _get_project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _candidate_secret_dirs() -> Iterable[Path]:
    custom_dir = os.getenv("SECRETS_KEYS_DIR")
    if custom_dir:
        yield Path(custom_dir)
    project_root = _get_project_root()
    yield project_root / "infra" / "secrets" / "keys"
    yield project_root / "secrets" / "keys"


def _load_secret_files_into_env() -> None:
    global _SECRETS_LOADED
    if _SECRETS_LOADED:
        return

    # Max size for environment variable values (most systems limit to ~128KB, but be conservative)
    MAX_ENV_VAR_SIZE = 32768  # 32KB

    for directory in _candidate_secret_dirs():
        if not directory.exists() or not directory.is_dir():
            continue

        for file_path in directory.iterdir():
            if not file_path.is_file():
                continue

            # Sanitize filename to create valid environment variable name
            # Replace any non-alphanumeric/underscore characters with underscores
            env_name = file_path.stem.upper()
            env_name = "".join(c if c.isalnum() or c == "_" else "_" for c in env_name)

            # Skip if empty name or already exists in environment
            if not env_name or env_name in os.environ:
                continue

            # Check file size before reading
            try:
                file_size = file_path.stat().st_size
                if file_size > MAX_ENV_VAR_SIZE:
                    logger.warning(
                        f"Secret file {file_path.name} is too large ({file_size} bytes) to load as environment variable (max {MAX_ENV_VAR_SIZE} bytes)"
                    )
                    continue
            except OSError as exc:
                logger.warning(
                    f"Unable to stat secret file {file_path}: {exc}"
                )
                continue

            # Read and validate content
            try:
                raw_value = file_path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning(
                    f"Unable to read secret file {file_path}: {exc}"
                )
                continue

            # Strip whitespace and validate
            value = raw_value.strip()
            if not value:
                continue

            # Final size check on actual content
            if len(value) > MAX_ENV_VAR_SIZE:
                logger.warning(
                    f"Secret file {file_path.name} content is too large ({len(value)} bytes) for environment variable (max {MAX_ENV_VAR_SIZE} bytes)"
                )
                continue

            # Set environment variable
            os.environ[env_name] = value
            logger.debug(
                f"Loaded secret {env_name} from {file_path.name} ({len(value)} bytes)"
            )

        break

    _SECRETS_LOADED = True


def substitute_env_vars(text: str) -> str:
    """
    Substitute environment variable placeholders in text.

    Supports formats:
    - ${VAR_NAME} - required variable (raises error if missing)
    - ${VAR_NAME:-default} - optional with default value
    - ${VAR_NAME:?error_message} - required with custom error message
    """

    _load_secret_files_into_env()

    def replacer(match):
        var_expr = match.group(1)

        # Handle default values: ${VAR:-default}
        if ":-" in var_expr:
            var_name, default = var_expr.split(":-", 1)
            return os.getenv(var_name, default)

        # Handle error messages: ${VAR:?message}
        elif ":?" in var_expr:
            var_name, error_msg = var_expr.split(":?", 1)
            value = os.getenv(var_name)
            if value is None:
                raise ValueError(f"Required environment variable {var_name}: {error_msg}")
            return value

        # Handle required variables: ${VAR}
        else:
            var_name = var_expr
            value = os.getenv(var_name)
            if value is None:
                raise ValueError(f"Required environment variable {var_name} not set")
            return value

    # Match ${...} patterns
    pattern = r'\$\{([^}]+)\}'
    return re.sub(pattern, replacer, text)
