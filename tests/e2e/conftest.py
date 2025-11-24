"""
Conftest for E2E tests.

E2E tests generate and test complete projects, so they should NOT
import fixtures from the template repository (which would trigger
config loading and require secrets in the template).

This empty conftest prevents the parent tests/conftest.py from being used.
"""
