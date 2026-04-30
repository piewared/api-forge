from loguru import logger
from sqlmodel import Session

from src.app.core.models.session import TokenClaims
from src.app.core.services.jwt.jwt_verify import JwtVerificationService
from src.app.core.services.session.user_session import UserSessionService
from src.app.entities.core.user.entity import User
from src.app.entities.core.user.repository import UserRepository
from src.app.entities.core.user_identity.entity import UserIdentity
from src.app.entities.core.user_identity.repository import UserIdentityRepository


class OrphanedIdentityError(LookupError):
    """A ``UserIdentity`` row points at a ``User`` that no longer exists.

    This is a data-integrity problem, not a client-input problem — callers
    typically map it to HTTP 500, distinct from invalid-claim 401s.
    """


class UserManagementService:
    def __init__(
        self,
        user_session_service: UserSessionService,
        jwt_service: JwtVerificationService,
        db_session: Session,
    ):
        self._user_session_service = user_session_service
        self._jwt_service = jwt_service
        self._user_repo = UserRepository(db_session)
        self._identity_repo = UserIdentityRepository(db_session)
        self._db_session = db_session

    async def provision_user_from_claims(self, claims: TokenClaims) -> User:
        """Provision user from OIDC claims (JIT provisioning).

        Args:
            claims: User claims from OIDC provider

        Returns:
            User object (created or existing)
        """
        try:
            issuer = claims.issuer
            subject = claims.subject

            if not issuer or not subject:
                raise ValueError("Missing required iss or sub claims")

            uid = claims.uid
            identity_repo = self._identity_repo
            user_repo = self._user_repo

            # Try to find existing identity
            identity = None
            if uid:
                identity = identity_repo.get_by_uid(uid)
            if identity is None:
                identity = identity_repo.get_by_issuer_subject(issuer, subject)

            if identity is None:
                # Create new user
                email = claims.email
                first_name = claims.given_name
                last_name = claims.family_name

                # Fallback name generation
                if not first_name and not last_name:
                    if email and "@" in email:
                        name_part = email.split("@")[0]
                        first_name = (
                            name_part.replace(".", " ").replace("_", " ").title()
                        )
                        last_name = ""
                    elif subject:
                        first_name = f"User {subject[-8:]}"
                        last_name = ""

                new_user = User(
                    first_name=first_name or "Unknown",
                    last_name=last_name or "User",
                    email=email,
                )

                created_user = user_repo.create(new_user)

                # Create identity mapping
                new_identity = UserIdentity(
                    issuer=issuer,
                    subject=subject,
                    uid_claim=uid,
                    user_id=created_user.id,
                )

                identity_repo.create(new_identity)
                self._db_session.commit()
                return created_user
            else:
                # Return existing user - but should we update their info?
                user = user_repo.get(identity.user_id)
                if user is None:
                    raise OrphanedIdentityError(
                        "User identity exists but user not found"
                    )

                # Update user with fresh claims data
                email = claims.email
                first_name = claims.given_name
                last_name = claims.family_name

                # Update user fields if they exist in claims
                updated = False
                if email and email != user.email:
                    user.email = email
                    updated = True
                if first_name and first_name != user.first_name:
                    user.first_name = first_name
                    updated = True
                if last_name and last_name != user.last_name:
                    user.last_name = last_name
                    updated = True

                if updated:
                    user_repo.update(user)
                    self._db_session.commit()

                return user
        except Exception as e:
            logger.error(f"Error during user provisioning: {e}")
            self._db_session.rollback()
            raise
