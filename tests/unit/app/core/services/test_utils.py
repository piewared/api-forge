import time

from src.app.core.services.jwt.jwt_utils import (
    create_token_claims,
    extract_roles,
    extract_scopes,
    extract_uid,
)
from src.app.runtime.config.config_data import ConfigData
from src.app.runtime.context import with_context


class TestJwtUtils:
    """Test JWT utility functions."""

    def test_extract_user_claims(
        self,
        test_identity_token_jwt,
        test_user_claims_dict,
        test_user_identity,
        test_user,
    ):
        claims = create_token_claims(
            token=test_identity_token_jwt,
            claims=test_user_claims_dict,
            token_type="id_token",
        )

        assert claims.issuer == test_user_identity.issuer
        assert claims.audience == "test-client-id"
        assert claims.subject == test_user_identity.subject
        assert claims.email == test_user.email
        assert claims.given_name == test_user.first_name
        assert claims.family_name == test_user.last_name

    def test_extract_uid_with_custom_claim(self):
        """Should extract UID from custom claim when configured."""
        claims = {"iss": "issuer", "sub": "subject", "custom_uid": "user-123"}

        # Create test config with custom uid claim
        test_config = ConfigData()
        test_config.jwt.claims.user_id = "custom_uid"

        with with_context(test_config):
            result = extract_uid(claims)
            assert result == "user-123"

    def test_extract_uid_fallback_to_issuer_subject(self):
        """Should fall back to issuer|subject when custom claim missing."""
        claims = {"iss": "https://issuer.example", "sub": "user-456"}

        # Create test config with missing uid claim
        test_config = ConfigData()
        test_config.jwt.claims.user_id = "missing_claim"

        with with_context(config_override=test_config):
            result = extract_uid(claims)
            assert result == "https://issuer.example|user-456"

    def test_extract_scopes_from_string(self):
        """Should parse space-separated scope string."""
        claims = {"scope": "read write admin"}

        result = extract_scopes(claims)
        assert result == ["read", "write", "admin"]

    def test_extract_scopes_from_list(self):
        """Should handle scope as list."""
        claims = {"scp": ["read", "write"]}

        result = extract_scopes(claims)
        assert result == ["read", "write"]

    def test_extract_scopes_from_multiple_sources(self):
        """Should combine scopes from multiple claim sources."""
        claims = {"scope": "read write", "scp": ["admin"]}

        result = extract_scopes(claims)
        assert result == ["read", "write", "admin"]

    def test_extract_roles_from_string(self):
        """Should parse space-separated roles string."""
        claims = {"roles": "user admin"}

        result = extract_roles(claims)
        assert set(result) == {"user", "admin"}

    def test_extract_roles_from_realm_access(self):
        """Should extract roles from Keycloak-style realm_access."""
        claims = {"realm_access": {"roles": ["admin", "user"]}, "roles": "guest"}

        result = extract_roles(claims)
        # Convert to set for comparison since order doesn't matter
        assert set(result) == {"admin", "user", "guest"}

    def test_extract_roles_from_singular_role_claim(self):
        """Should extract roles from singular 'role' claim."""
        # Test single role as string
        claims1 = {"role": "admin"}
        result1 = extract_roles(claims1)
        assert result1 == ["admin"]

        # Test multiple roles in singular claim (space-separated)
        claims2 = {"role": "user moderator"}
        result2 = extract_roles(claims2)
        assert set(result2) == {"user", "moderator"}

        # Test role and roles together (should combine both)
        claims3 = {"role": "admin", "roles": ["user", "guest"]}
        result3 = extract_roles(claims3)
        assert set(result3) == {"admin", "user", "guest"}

    def test_extract_empty_claims(self):
        """Should handle missing or empty claims gracefully."""
        claims = {}

        assert extract_uid(claims) == "None|None"
        assert extract_scopes(claims) == []
        assert extract_roles(claims) == []

    def test_create_token_claims_preserves_unmapped_claims(self):
        """Should preserve unmapped claims in custom_claims without dropping standard claims."""
        # Test with a mix of mapped and unmapped claims
        claims = {
            # Mapped claims (should be extracted to TokenClaims fields)
            "sub": "user-123",
            "iss": "https://test.issuer",
            "aud": ["api://test"],
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "nbf": int(time.time()),
            "email": "user@example.com",
            "name": "John Doe",
            "given_name": "John",
            "family_name": "Doe",
            "nonce": "abc123",
            "scope": "read write",
            "roles": ["user", "admin"],
            # Standard claims that we don't have TokenClaims fields for (should stay in custom_claims)
            "jti": "unique-jwt-id",
            "auth_time": 1234567890,
            "azp": "authorized-party",
            "acr": "0",
            "amr": ["pwd"],
            "at_hash": "access-token-hash",
            "middle_name": "Robert",
            "nickname": "Johnny",
            "preferred_username": "john_doe",
            "profile": "https://example.com/profile",
            "picture": "https://example.com/photo.jpg",
            "website": "https://johndoe.com",
            "gender": "male",
            "birthdate": "1990-01-01",
            "zoneinfo": "America/New_York",
            "locale": "en-US",
            "updated_at": 1234567890,
            "email_verified": True,
            "phone_number": "+1234567890",
            "phone_number_verified": True,
            "address": {"street": "123 Main St", "city": "Anytown"},
            # Truly custom claims (should stay in custom_claims)
            "tenant_id": "org-456",
            "permissions": ["read:documents", "write:reports"],
            "custom_field": "custom_value",
            "organization": {"id": "org-123", "name": "Acme Corp"},
        }

        token_claims = create_token_claims(
            token="test.jwt.token",
            claims=claims,
            token_type="access_token",
            issuer="fallback-issuer",
        )

        # Verify that mapped claims are correctly extracted
        assert token_claims.subject == "user-123"
        assert token_claims.issuer == "https://test.issuer"
        assert token_claims.audience == ["api://test"]
        assert token_claims.email == "user@example.com"
        assert token_claims.name == "John Doe"
        assert token_claims.given_name == "John"
        assert token_claims.family_name == "Doe"
        assert token_claims.nonce == "abc123"
        assert token_claims.scope == "read write"
        assert set(token_claims.scopes) == {"read", "write"}
        assert set(token_claims.roles) == {"user", "admin"}

        # Verify that all unmapped claims are preserved in custom_claims
        expected_custom_claims = {
            # Standard claims we don't have fields for
            "auth_time": 1234567890,
            "acr": "0",
            "amr": ["pwd"],
            "at_hash": "access-token-hash",
            "middle_name": "Robert",
            "nickname": "Johnny",
            "preferred_username": "john_doe",
            "profile": "https://example.com/profile",
            "picture": "https://example.com/photo.jpg",
            "website": "https://johndoe.com",
            "gender": "male",
            "birthdate": "1990-01-01",
            "zoneinfo": "America/New_York",
            "locale": "en-US",
            "updated_at": 1234567890,
            "phone_number": "+1234567890",
            "phone_number_verified": True,
            "address": {"street": "123 Main St", "city": "Anytown"},
            # Truly custom claims
            "tenant_id": "org-456",
            "permissions": ["read:documents", "write:reports"],
            "custom_field": "custom_value",
            "organization": {"id": "org-123", "name": "Acme Corp"},
        }

        assert token_claims.custom_claims == expected_custom_claims

        # Verify that all_claims contains the original claims unchanged
        assert token_claims.all_claims == claims
