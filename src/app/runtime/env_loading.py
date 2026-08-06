"""Single source of truth for project ``.env`` loading.

Precedence (python-dotenv ``override=False``: first-seen wins):
**shell environment > ``.env.dev`` (development only) > ``.env``**.

Every process that parses ``config.yaml`` must load env through this
helper first: config substitution fails fast on required variables
with no default (e.g. OIDC client secrets), and ``.env.dev`` is what
supplies the dev placeholders for them. Scattered bare
``load_dotenv()`` calls are exactly how the dev worker and
``dev db migrate`` ended up crashing on ``OIDC_GOOGLE_CLIENT_SECRET``
while the dev API ran fine.

The docker-compose dev stack mirrors this precedence via ``env_file``
(there, the *later* file wins, so the list is ``.env`` then
``.env.dev``).
"""

import os
from pathlib import Path

from dotenv import load_dotenv


def load_project_env(
    project_root: Path | None = None,
    environment: str | None = None,
) -> None:
    """Load ``.env`` files with the canonical precedence.

    Args:
        project_root: Directory containing the env files; defaults to
            the current working directory.
        environment: Explicit environment name for call sites that
            know their context (dev CLI commands pass
            ``"development"``, prod config loading passes
            ``"production"``); defaults to ``APP_ENVIRONMENT``.
            ``.env.dev`` loads only for ``development``.
    """
    root = project_root or Path.cwd()
    env = environment or os.environ.get("APP_ENVIRONMENT")
    if env == "development":
        load_dotenv(root / ".env.dev", override=False)
    load_dotenv(root / ".env", override=False)
