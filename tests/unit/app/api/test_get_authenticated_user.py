"""Unit tests for the unified ``get_authenticated_user`` dependency.

This dep is the auth seam for every protected endpoint that accepts JWT (i.e.,
non-BFF API/mobile clients). Two paths run through it:

1. Session cookie path — exercised implicitly via the BFF tests; covered here
   by a single priority test (session wins when both session and Bearer present).
2. JWT Bearer path — covered exhaustively here, including JIT user provisioning,
   name-derivation fallbacks, and the failure modes.

The session services are mocked because they're not what's under test; the JWT
verifier is mocked because we don't need to mint real tokens; the database is a
real in-memory SQLite session so the User / UserIdentity repos run against real
SQL and exercise the full provisioning flow.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from src.app.api.http.deps import (
    get_authenticated_user,
    get_db_session,
    get_jwt_verify_service,
    get_user_session_service,
)
from src.app.core.models.session import TokenClaims
from src.app.entities.core.user import User, UserRepository
from src.app.entities.core.user_identity import UserIdentity, UserIdentityRepository

# ---------- Fixtures ----------


def _make_claims(
    *,
    issuer: str | None = "https://idp.test",
    subject: str | None = "subject-1",
    uid: str | None = None,
    email: str | None = "user@example.com",
    given_name: str | None = "Given",
    family_name: str | None = "Family",
    scopes: list[str] | None = None,
    roles: list[str] | None = None,
) -> TokenClaims:
    now = int(time.time())
    return TokenClaims(
        # Pydantic complains if iss/sub are None — but the route-side validation
        # is what we want to test, so pass empty string when "missing" requested.
        issuer=issuer or "",
        subject=subject or "",
        audience="api://test",
        uid=uid,
        email=email,
        given_name=given_name,
        family_name=family_name,
        scopes=scopes or [],
        roles=roles or [],
        expires_at=now + 3600,
        issued_at=now,
    )


@pytest.fixture
def jwt_verify_service() -> AsyncMock:
    """The verifier whose verify_jwt(token) the dep calls."""
    return AsyncMock()


@pytest.fixture
def user_session_service() -> AsyncMock:
    """Mocked: the session path is not under test here.

    Default behavior — no session cookie set, so get_user_session is never
    invoked. Tests that *want* the session path active set their own return.
    """
    return AsyncMock()


@pytest.fixture
def auth_app(
    session: Session,
    jwt_verify_service: AsyncMock,
    user_session_service: AsyncMock,
) -> FastAPI:
    """Minimal app with one protected route that returns the resolved user.id."""
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(user: User = Depends(get_authenticated_user)) -> dict[str, str]:
        return {"id": str(user.id), "email": user.email or ""}

    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_jwt_verify_service] = lambda: jwt_verify_service
    app.dependency_overrides[get_user_session_service] = lambda: user_session_service
    return app


@pytest.fixture
def auth_client(auth_app: FastAPI) -> Generator[TestClient]:
    yield TestClient(auth_app)


# ---------- JWT path: happy + provisioning ----------


class TestJWTAuthExistingUser:
    def test_returns_existing_user_when_identity_known(
        self,
        auth_client: TestClient,
        session: Session,
        jwt_verify_service: AsyncMock,
    ) -> None:
        existing_user = User(
            first_name="Old", last_name="User", email="old@example.com"
        )
        UserRepository(session).create(existing_user)
        UserIdentityRepository(session).create(
            UserIdentity(
                issuer="https://idp.test",
                subject="subject-1",
                uid_claim=None,
                user_id=existing_user.id,
            )
        )
        session.commit()

        jwt_verify_service.verify_jwt.return_value = _make_claims(
            issuer="https://idp.test", subject="subject-1"
        )

        response = auth_client.get("/whoami", headers={"Authorization": "Bearer token"})

        assert response.status_code == 200
        assert response.json()["id"] == str(existing_user.id)

    def test_lookup_by_uid_takes_precedence_over_issuer_subject(
        self,
        auth_client: TestClient,
        session: Session,
        jwt_verify_service: AsyncMock,
    ) -> None:
        """If the JWT has a uid claim, the dep looks up by uid first; falling
        back to (issuer, subject) only if uid yields no identity."""
        target_user = User(first_name="UID", last_name="User", email="uid@example.com")
        UserRepository(session).create(target_user)
        UserIdentityRepository(session).create(
            UserIdentity(
                issuer="https://idp.test",
                subject="subject-uid",
                uid_claim="custom-uid-123",
                user_id=target_user.id,
            )
        )
        session.commit()

        jwt_verify_service.verify_jwt.return_value = _make_claims(
            uid="custom-uid-123",
            issuer="https://idp.test",
            subject="different-subject",  # Wrong subject — uid lookup must win.
        )

        response = auth_client.get("/whoami", headers={"Authorization": "Bearer token"})

        assert response.status_code == 200
        assert response.json()["id"] == str(target_user.id)


class TestJITProvisioning:
    """When the JWT is valid but no identity exists, the dep creates a User
    and a UserIdentity row — this is the JIT provisioning seam."""

    def test_creates_user_from_full_claims(
        self,
        auth_client: TestClient,
        session: Session,
        jwt_verify_service: AsyncMock,
    ) -> None:
        jwt_verify_service.verify_jwt.return_value = _make_claims(
            email="new@example.com", given_name="New", family_name="Person"
        )

        response = auth_client.get("/whoami", headers={"Authorization": "Bearer token"})
        assert response.status_code == 200
        assert response.json()["email"] == "new@example.com"

        # The identity row was actually persisted.
        identity = UserIdentityRepository(session).get_by_issuer_subject(
            "https://idp.test", "subject-1"
        )
        assert identity is not None
        user = UserRepository(session).get(identity.user_id)
        assert user is not None
        assert user.first_name == "New"
        assert user.last_name == "Person"

    def test_falls_back_to_email_local_part_for_name(
        self,
        auth_client: TestClient,
        session: Session,
        jwt_verify_service: AsyncMock,
    ) -> None:
        """Without given_name/family_name, the dep derives a first name from
        the email's local part (titlecased, with . / _ → spaces)."""
        jwt_verify_service.verify_jwt.return_value = _make_claims(
            email="jane.q.public@example.com",
            given_name=None,
            family_name=None,
        )

        response = auth_client.get("/whoami", headers={"Authorization": "Bearer token"})
        assert response.status_code == 200

        identity = UserIdentityRepository(session).get_by_issuer_subject(
            "https://idp.test", "subject-1"
        )
        assert identity is not None
        user = UserRepository(session).get(identity.user_id)
        assert user is not None
        assert user.first_name == "Jane Q Public"

    def test_falls_back_to_subject_when_no_email_no_names(
        self,
        auth_client: TestClient,
        session: Session,
        jwt_verify_service: AsyncMock,
    ) -> None:
        """No email and no name claims — uses last 8 chars of subject."""
        jwt_verify_service.verify_jwt.return_value = _make_claims(
            email=None,
            given_name=None,
            family_name=None,
            subject="long-subject-with-tail",
        )

        response = auth_client.get("/whoami", headers={"Authorization": "Bearer token"})
        assert response.status_code == 200

        identity = UserIdentityRepository(session).get_by_issuer_subject(
            "https://idp.test", "long-subject-with-tail"
        )
        assert identity is not None
        user = UserRepository(session).get(identity.user_id)
        assert user is not None
        # Last 8 chars of "long-subject-with-tail" is "ith-tail".
        assert user.first_name == "User ith-tail"


# ---------- JWT path: failure modes ----------


class TestJWTAuthFailureModes:
    def test_missing_issuer_returns_401(
        self, auth_client: TestClient, jwt_verify_service: AsyncMock
    ) -> None:
        jwt_verify_service.verify_jwt.return_value = _make_claims(issuer=None)

        response = auth_client.get("/whoami", headers={"Authorization": "Bearer token"})

        assert response.status_code == 401
        assert "missing required" in response.json()["detail"].lower()

    def test_missing_subject_returns_401(
        self, auth_client: TestClient, jwt_verify_service: AsyncMock
    ) -> None:
        jwt_verify_service.verify_jwt.return_value = _make_claims(subject=None)

        response = auth_client.get("/whoami", headers={"Authorization": "Bearer token"})

        assert response.status_code == 401

    def test_identity_exists_but_user_missing_returns_500(
        self,
        auth_client: TestClient,
        session: Session,
        jwt_verify_service: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Data integrity: an identity row resolves to a user_id whose User row
        cannot be read back. The dep must surface this as 500, not silently
        re-provision.

        The identity is persisted against a real user because ``user_id`` is a
        NOT NULL foreign key — an orphan row is rejected by the database. The
        lost-user condition this branch defends against (the user disappearing
        between the identity lookup and the user fetch) is injected at the
        repository instead.
        """
        owner = UserRepository(session).create(
            User(first_name="Orphan", last_name="Owner", email="orphan@example.com")
        )
        UserIdentityRepository(session).create(
            UserIdentity(
                issuer="https://idp.test",
                subject="orphan-subject",
                uid_claim=None,
                user_id=owner.id,
            )
        )
        session.commit()

        monkeypatch.setattr(UserRepository, "get", lambda self, entity_id: None)

        jwt_verify_service.verify_jwt.return_value = _make_claims(
            subject="orphan-subject"
        )

        response = auth_client.get("/whoami", headers={"Authorization": "Bearer token"})

        assert response.status_code == 500
        assert "user not found" in response.json()["detail"].lower()

    def test_jwt_verification_failure_returns_401(
        self, auth_client: TestClient, jwt_verify_service: AsyncMock
    ) -> None:
        """If verify_jwt raises (signature invalid, expired, etc.), the dep
        catches it and falls through to the generic "Authentication required"
        401 — it does not leak the specific verification error."""
        jwt_verify_service.verify_jwt.side_effect = ValueError("bad signature")

        response = auth_client.get("/whoami", headers={"Authorization": "Bearer token"})

        assert response.status_code == 401
        assert "authentication required" in response.json()["detail"].lower()


# ---------- No auth at all ----------


class TestNoAuth:
    def test_no_session_no_bearer_returns_401(self, auth_client: TestClient) -> None:
        response = auth_client.get("/whoami")

        assert response.status_code == 401
        assert "authentication required" in response.json()["detail"].lower()

    def test_non_bearer_authorization_header_returns_401(
        self, auth_client: TestClient
    ) -> None:
        """Authorization header without 'Bearer ' prefix is ignored — falls
        through to the no-auth branch."""
        response = auth_client.get(
            "/whoami", headers={"Authorization": "Basic dXNlcjpwYXNz"}
        )

        assert response.status_code == 401


# ---------- Auth method priority ----------


class TestAuthMethodPriority:
    def test_session_takes_priority_over_bearer_token(
        self,
        auth_client: TestClient,
        session: Session,
        user_session_service: AsyncMock,
        jwt_verify_service: AsyncMock,
    ) -> None:
        """When a request carries BOTH a session cookie and a Bearer token,
        the session wins — JWT verification is never invoked."""
        from src.app.core.models.session import UserSession

        session_user = User(
            first_name="Session", last_name="User", email="session@example.com"
        )
        UserRepository(session).create(session_user)
        session.commit()

        now = int(time.time())
        user_session_service.get_user_session.return_value = UserSession(
            id="session-id",
            user_id=str(session_user.id),
            provider="default",
            client_fingerprint="fp",
            access_token=None,
            refresh_token=None,
            access_token_expires_at=None,
            created_at=now,
            last_accessed_at=now,
            expires_at=now + 3600,
        )

        auth_client.cookies.set("user_session_id", "session-id")
        response = auth_client.get("/whoami", headers={"Authorization": "Bearer token"})

        assert response.status_code == 200
        assert response.json()["id"] == str(session_user.id)
        # The dep returned via the session path; verifier was never called.
        jwt_verify_service.verify_jwt.assert_not_awaited()
