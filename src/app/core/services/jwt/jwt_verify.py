"""JWT verification service."""

import time

from authlib.jose import JoseError, JsonWebKey, KeySet, jwt
from fastapi import HTTPException
from loguru import logger

from src.app.core.models.session import TokenClaims
from src.app.core.services.jwt.jwks import JwksService
from src.app.core.services.jwt.jwt_utils import (
    JwtPreview,
    create_token_claims,
    lookup_config_by_issuer,
    preview_jwt,
)
from src.app.runtime.context import get_config


# ---------------------------- helpers ---------------------------------
def _as_list(v: str | list[str] | None) -> list[str]:
    return [v] if isinstance(v, str) else list(v or ())


class JwtVerificationService:
    def __init__(self, jwks_service: JwksService):
        self._jwks_service = jwks_service

    async def verify_jwt(
        self,
        token: str,
        *,
        key: str | None = None,
        expected_audience: list[str] | str | None = None,
        expected_nonce: str | None = None,
        expected_issuer: str | None = None,
        preview: JwtPreview | None = None,
    ) -> TokenClaims:
        cfg = get_config()
        pv = preview or preview_jwt(token)

        # Type for verification key can be string (internal) or KeySet (OIDC)
        verification_key: str | KeySet

        # alg allowlist
        if pv.alg not in cfg.jwt.allowed_algorithms:
            raise HTTPException(status_code=401, detail="Disallowed JWT algorithm")

        internal = True
        provider_cfg = None

        if key is None:
            if pv.iss:
                exp_iss = (
                    expected_issuer.rstrip("/")
                    if isinstance(expected_issuer, str)
                    else None
                )
                if exp_iss or pv.iss:
                    if exp_iss and pv.iss != exp_iss:
                        raise HTTPException(status_code=401, detail="Invalid issuer")

                    # resolve provider by exact issuer match if not explicitly given
                    provider_cfg = lookup_config_by_issuer(exp_iss or pv.iss)
                    if provider_cfg:
                        internal = False
                else:
                    raise HTTPException(status_code=401, detail="No issuer")
            else:
                raise HTTPException(status_code=401, detail="Missing iss claim")

        if internal:
            temp_key = key or cfg.app.session_signing_secret
            if not temp_key:
                raise HTTPException(
                    status_code=500, detail="JWT signing secret not configured"
                )
            verification_key = temp_key  # Now guaranteed to be str
            claims_options = None
            provider_cfg = None
        else:
            if provider_cfg is None:
                raise HTTPException(status_code=401, detail=f"Unknown issuer: {pv.iss}")

            # audience allowlist. Combine configured audiences with client_id
            aud_values = (
                _as_list(expected_audience)
                + _as_list(cfg.jwt.audiences)
                + _as_list(provider_cfg.client_id)
            )
            if not aud_values:
                raise HTTPException(
                    status_code=401, detail="No expected audience configured"
                )

            claims_options = {
                "iss": {"essential": True, "values": [provider_cfg.issuer.rstrip("/")]},
                "aud": {"essential": True, "values": aud_values},
            }

            # fetch JWKS and select by kid once
            jwks = await self._jwks_service.fetch_jwks(provider_cfg)
            jwk_set = (
                {"keys": [k for k in jwks.get("keys", []) if k.get("kid") == pv.kid]}
                if pv.kid
                else jwks
            )
            if pv.kid and not jwk_set.get("keys"):
                jwks = await self._jwks_service.fetch_jwks(
                    provider_cfg, force_refresh=True
                )
                jwk_set = {
                    "keys": [k for k in jwks.get("keys", []) if k.get("kid") == pv.kid]
                }
                if not jwk_set.get("keys"):
                    raise HTTPException(
                        status_code=401, detail=f"No JWK matches kid={pv.kid}"
                    )
            verification_key = JsonWebKey.import_key_set(jwk_set)

        # verify signature + registered claims
        try:
            if claims_options:
                iss_values = claims_options["iss"].get("values", [])
                issuer_values: list[str] = iss_values if isinstance(iss_values, list) else []
                aud_values_obj = claims_options["aud"].get("values", [])
                aud_count = len(aud_values_obj) if isinstance(aud_values_obj, list) else 0
                logger.debug(
                    "Verifying JWT from issuer=%s with %d expected audiences",
                    issuer_values[0] if issuer_values else "unknown",
                    aud_count,
                )
            else:
                logger.debug("Verifying internal JWT without issuer/audience checks")

            claims = jwt.decode(token, verification_key, claims_options=claims_options)
            claims.validate(leeway=cfg.jwt.clock_skew)
        except (JoseError, ValueError) as exc:
            raise HTTPException(status_code=401, detail=f"JWT error: {exc}") from exc

        # extra temporal sanity
        now = int(time.time())
        for k, check in (
            ("exp", lambda v: now > int(v) + cfg.jwt.clock_skew),
            ("nbf", lambda v: now < int(v) - cfg.jwt.clock_skew),
            ("iat", lambda v: int(v) > now + cfg.jwt.clock_skew),
        ):
            v = claims.get(k)
            if v is not None and check(v):
                raise HTTPException(status_code=401, detail=f"Invalid {k} with skew")

        # oidc-specific
        if not internal:
            if not provider_cfg:
                raise HTTPException(status_code=401, detail="Unknown OIDC provider")

            if expected_nonce is not None:
                tok_nonce = claims.get("nonce")
                if not tok_nonce or tok_nonce != expected_nonce:
                    raise HTTPException(status_code=401, detail="Invalid/missing nonce")
            aud_list = _as_list(claims.get("aud"))
            logger.debug(
                "Token audience count=%d, azp_present=%s, expected_audience_count=%d",
                len(aud_list),
                bool(claims.get("azp")),
                len(_as_list(expected_audience)) if expected_audience else 0,
            )

            azp = claims.get("azp")
            # If azp is present and aud claim is a single entry string, azp must match client_id. If azp is present and aud is a list, azp must match one of the audiences in the list.
            if azp:
                if isinstance(claims.get("aud"), str):
                    if azp != (expected_audience or provider_cfg.client_id):
                        raise HTTPException(
                            status_code=401,
                            detail="Invalid azp for single-audience token",
                        )
                elif isinstance(claims.get("aud"), list):
                    if azp not in _as_list(aud_list or provider_cfg.client_id):
                        raise HTTPException(
                            status_code=401,
                            detail="Invalid azp for multi-audience token",
                        )
                else:
                    raise HTTPException(
                        status_code=401, detail="Invalid aud claim format"
                    )

            # If azp is not present and aud claim is a list with multiple entries, this is an error.
            if not azp and len(aud_list) > 1:
                raise HTTPException(
                    status_code=401, detail="Missing azp for multi-audience token"
                )

        if not claims.get("sub"):
            raise HTTPException(status_code=401, detail="Missing sub claim")

        token_type = (
            "id_token"
            if ("nonce" in claims or expected_nonce is not None)
            else "access_token"
        )
        return create_token_claims(
            token=token, claims=claims, token_type=token_type, issuer=claims.get("iss")
        )

    async def verify_generated_jwt(self, token: str) -> TokenClaims:
        """Verify a JWT token generated by this service.

        Convenience function that calls verify_jwt with the local secret key.
        This maintains backward compatibility while using the unified verification logic.

        Args:
            token: JWT token to verify

        Returns:
            Verified claims dictionary

        Raises:
            HTTPException: If verification fails
        """

        config = get_config()
        secret = config.app.session_signing_secret
        if not secret:
            raise HTTPException(
                status_code=500, detail="JWT signing secret not configured"
            )

        # Use string key for consistency with type hints
        secret_key = secret if isinstance(secret, str) else secret.decode()

        # Call the unified verify_jwt function with the local secret
        return await self.verify_jwt(token, key=secret_key)
