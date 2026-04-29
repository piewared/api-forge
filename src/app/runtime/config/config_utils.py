import os
import re
from pathlib import Path

from loguru import logger

from src.infra.secrets import FileSecretsManager
from src.utils.paths import get_project_root

_SECRETS_LOADED = False


def _candidate_secret_dirs() -> list[Path]:
    """Get candidate directories for secrets files."""
    dirs: list[Path] = []
    custom_dir = os.getenv("SECRETS_KEYS_DIR")
    if custom_dir:
        dirs.append(Path(custom_dir))
    project_root = get_project_root()
    dirs.append(project_root / "infra" / "secrets" / "keys")
    dirs.append(project_root / "secrets" / "keys")
    return dirs


def load_secret_files_into_env() -> None:
    """Load secret files into environment variables.

    Uses FileSecretsManager to read secrets and populate environment variables.
    Each secret key becomes an uppercase environment variable name.
    """
    global _SECRETS_LOADED
    if _SECRETS_LOADED:
        return

    # Max size for environment variable values (most systems limit to ~128KB, but be conservative)
    MAX_ENV_VAR_SIZE = 32768  # 32KB

    for directory in _candidate_secret_dirs():
        if not directory.exists() or not directory.is_dir():
            continue

        # Use FileSecretsManager for this directory
        manager = FileSecretsManager(secrets_dir=directory)
        keys = manager.list_keys()

        for key in keys:
            # Convert key to env var name (uppercase, sanitize)
            env_name = key.upper()
            env_name = "".join(c if c.isalnum() or c == "_" else "_" for c in env_name)

            # Skip if empty name or already exists in environment
            if not env_name:
                continue

            if env_name in os.environ:
                continue

            # Read secret value using SecretsManager
            try:
                value = manager.read(key)
                if not value:
                    continue
            except OSError as exc:
                logger.warning(f"Unable to read secret {key}: {exc}")
                continue

            # Size check on content
            if len(value) > MAX_ENV_VAR_SIZE:
                logger.warning(
                    f"Secret {key} content is too large ({len(value)} bytes) for environment variable (max {MAX_ENV_VAR_SIZE} bytes)"
                )
                continue

            # Set environment variable
            os.environ[env_name] = value
            logger.debug(
                f"Loaded secret {env_name} from {key}.txt ({len(value)} bytes)"
            )

        # Only use first existing directory
        break

    _SECRETS_LOADED = True


def _strip_inline_comment(value: str) -> str:
    """
    Strip inline comments from environment variable values.

    Handles comments starting with # (ignoring escaped \\#).
    Preserves the value before the comment and strips trailing whitespace.

    Examples:
        "3600  # Session max age" -> "3600"
        "value # comment" -> "value"
        "no comment here" -> "no comment here"
    """
    # Find first unescaped # character
    comment_pattern = r"\s*(?<!\\)#.*$"
    return re.sub(comment_pattern, "", value).strip()


def substitute_env_vars(text: str) -> str:
    """
    Substitute environment variable placeholders in text.

    Supports formats:
    - ${VAR_NAME} - required variable (raises error if missing)
    - ${VAR_NAME:-default} - optional with default value
    - ${VAR_NAME:?error_message} - required with custom error message

    Note: Environment variable values are automatically stripped of inline comments.
    """

    load_secret_files_into_env()

    def replacer(match: re.Match[str]) -> str:
        var_expr = match.group(1)

        # Handle default values: ${VAR:-default}
        if ":-" in var_expr:
            var_name, default = var_expr.split(":-", 1)
            value = os.getenv(var_name, default)
            return _strip_inline_comment(value)

        # Handle error messages: ${VAR:?message}
        elif ":?" in var_expr:
            var_name, error_msg = var_expr.split(":?", 1)
            value = os.getenv(var_name)
            if value is None:
                raise ValueError(
                    f"Required environment variable {var_name}: {error_msg}"
                )
            return _strip_inline_comment(value)

        # Handle required variables: ${VAR}
        else:
            var_name = var_expr
            value = os.getenv(var_name)
            if value is None:
                raise ValueError(f"Required environment variable {var_name} not set")
            return _strip_inline_comment(value)

    # Match ${...} patterns
    pattern = r"\$\{([^}]+)\}"
    return re.sub(pattern, replacer, text)
