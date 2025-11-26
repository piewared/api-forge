from typing import Any

from pydantic import BaseModel


class JwtClaims(BaseModel):
    """Canonical representation of JWT claims used across the app."""

    iss: str
    sub: str
    aud: str | None = None
    exp: int | None = None
    nbf: int | None = None
    scope: str | None = None
    scp: list[str] | None = None
    roles: list[str] | None = None
    realm_access: dict[str, Any] | None = None

    def scopes(self) -> set[str]:
        scopes: set[str] = set()
        if self.scope:
            scopes.update(self.scope.split())
        if self.scp:
            scopes.update(self.scp)
        return scopes

    def roles_list(self) -> set[str]:
        roles: set[str] = set(self.roles or [])
        realm = self.realm_access or {}
        if isinstance(realm.get("roles"), list):
            roles.update(realm["roles"])
        return roles
