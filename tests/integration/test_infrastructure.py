"""Consolidated infrastructure and configuration tests.

This module combines and consolidates tests for:
- Settings and environment variable handling
- Context manager and configuration management
- Application startup and infrastructure components

"""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.app.runtime.context import get_config


class TestApplicationStartup:
    """Test application startup and initialization."""

    def test_app_creation(self):
        """Test that the FastAPI app can be created."""
        from src.app.api.http.app import app

        assert app is not None
        assert hasattr(app, "routes")
        assert len(app.routes) > 0

    def test_middleware_configuration(self):
        """Test that middleware is properly configured."""
        from src.app.api.http.app import app

        # Check that middleware is applied
        middleware_types = [
            type(middleware.cls).__name__ for middleware in app.user_middleware
        ]

        # Should have CORS and potentially other middleware
        assert len(middleware_types) > 0

    def test_environment_configuration_loaded(self):
        """Test that environment-specific configuration is loaded."""
        config = get_config()

        # Basic configuration should be loaded
        assert config.app.environment in ["development", "test", "production"]
        assert isinstance(config.jwt.allowed_algorithms, list)
        assert len(config.jwt.allowed_algorithms) > 0


class TestInfrastructureIntegration:
    """Test integrated infrastructure functionality."""

    def test_dependency_injection_chain(self):
        """Test that dependency injection works for complex chains."""
        from src.app.api.http.deps import get_db_session

        # Should be able to get session factory
        assert get_db_session is not None
        assert callable(get_db_session)



    def test_error_handling_integration(self, auth_test_client: TestClient):
        """Test that error handling works across the system."""
        # Try to access non-existent endpoint
        response = auth_test_client.get("/nonexistent-endpoint")
        assert response.status_code == 404
