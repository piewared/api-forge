import os

# Set test mode flag BEFORE any imports that might load config
# This allows config loading to use test defaults instead of requiring all env vars
os.environ.setdefault("PYTEST_RUNNING", "1")

# Set minimal required env vars for config loading in tests
# These are only used if not already set (e.g., by integration tests that need real values)
os.environ.setdefault("OIDC_GOOGLE_CLIENT_SECRET", "test-secret-google")
os.environ.setdefault("OIDC_MICROSOFT_CLIENT_SECRET", "test-secret-microsoft")
os.environ.setdefault("OIDC_KEYCLOAK_CLIENT_SECRET", "test-secret-keycloak")
os.environ.setdefault("SESSION_SIGNING_SECRET", "test-session-secret-32-bytes-long")
os.environ.setdefault("CSRF_SIGNING_SECRET", "test-csrf-secret-32-bytes-long-")

from tests.fixtures import *  # noqa: F401,F403
