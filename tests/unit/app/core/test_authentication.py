"""Tests for the require_scope and require_role authorization dependencies."""

from unittest.mock import Mock

import pytest
from fastapi import HTTPException, Request

from src.app.api.http.deps import require_role, require_scope


class TestAuthenticationDependencies:
    """Test authentication and authorization dependency functions."""

    def create_mock_request(
        self, scopes: list[str] | None = None, roles: list[str] | None = None
    ) -> Request:
        """Create mock request with auth context."""
        request = Mock(spec=Request)
        request.state = Mock()

        if scopes is not None:
            request.state.scopes = set(scopes)
        if roles is not None:
            request.state.roles = set(roles)

        return request

    @pytest.mark.asyncio
    async def test_require_scope_success(self):
        """Test scope requirement with valid scope."""
        request = self.create_mock_request(scopes=["read", "write", "admin"])

        scope_dep = require_scope("read")
        # Should not raise for valid scope
        await scope_dep(request)

        scope_dep_write = require_scope("write")
        await scope_dep_write(request)

    @pytest.mark.asyncio
    async def test_require_scope_failure(self):
        """Test scope requirement with missing scope."""
        request = self.create_mock_request(scopes=["read"])

        scope_dep = require_scope("admin")

        with pytest.raises(HTTPException) as exc_info:
            await scope_dep(request)

        assert exc_info.value.status_code == 403
        assert "Missing required scope: admin" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_scope_empty_scopes(self):
        """Test scope requirement with empty scopes set."""
        request = self.create_mock_request(scopes=[])

        scope_dep = require_scope("read")

        with pytest.raises(HTTPException) as exc_info:
            await scope_dep(request)

        assert exc_info.value.status_code == 403
        assert "Missing required scope: read" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_scope_missing_scopes_attribute(self):
        """Test scope requirement when scopes attribute is missing from state."""
        request = Mock(spec=Request)

        # Create a simple object without the scopes attribute
        class SimpleState:
            pass

        request.state = SimpleState()

        scope_dep = require_scope("read")

        with pytest.raises(HTTPException) as exc_info:
            await scope_dep(request)

        assert exc_info.value.status_code == 403
        assert "Missing required scope: read" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_role_success(self):
        """Test role requirement with valid role."""
        request = self.create_mock_request(roles=["user", "admin", "moderator"])

        role_dep = require_role("admin")
        # Should not raise for valid role
        await role_dep(request)

        role_dep_user = require_role("user")
        await role_dep_user(request)

    @pytest.mark.asyncio
    async def test_require_role_failure(self):
        """Test role requirement with missing role."""
        request = self.create_mock_request(roles=["user"])

        role_dep = require_role("admin")

        with pytest.raises(HTTPException) as exc_info:
            await role_dep(request)

        assert exc_info.value.status_code == 403
        assert "Missing required role: admin" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_role_empty_roles(self):
        """Test role requirement with empty roles set."""
        request = self.create_mock_request(roles=[])

        role_dep = require_role("user")

        with pytest.raises(HTTPException) as exc_info:
            await role_dep(request)

        assert exc_info.value.status_code == 403
        assert "Missing required role: user" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_role_missing_roles_attribute(self):
        """Test role requirement when roles attribute is missing from state."""
        request = Mock(spec=Request)

        # Create a simple object without the roles attribute
        class SimpleState:
            pass

        request.state = SimpleState()

        role_dep = require_role("user")

        with pytest.raises(HTTPException) as exc_info:
            await role_dep(request)

        assert exc_info.value.status_code == 403
        assert "Missing required role: user" in exc_info.value.detail
