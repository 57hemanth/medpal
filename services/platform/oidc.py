"""OIDC bearer token verification."""

from functools import lru_cache
from typing import Any, cast

import jwt
from jwt import PyJWKClient

from .auth import ROLES, AuthContext
from .config import Settings


class OidcError(ValueError):
    pass


@lru_cache(maxsize=8)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url)


def verify_token(token: str, settings: Settings) -> AuthContext:
    if not settings.oidc_issuer or not settings.oidc_audience or not settings.oidc_jwks_url:
        raise OidcError("OIDC issuer, audience and JWKS URL must be configured")
    key = _jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token).key
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
        )
    except jwt.PyJWTError as exc:
        raise OidcError("invalid OIDC token") from exc
    return context_from_claims(cast(dict[str, Any], claims))


def context_from_claims(claims: dict[str, Any]) -> AuthContext:
    role = claims.get("medpal_role") or claims.get("role")
    user_id = claims.get("sub")
    if role not in ROLES or not isinstance(user_id, str):
        raise OidcError("token is missing MedPal role or subject")
    patient_id = claims.get("medpal_patient_id") if role == "patient" else None
    return AuthContext(user_id=user_id, role=role, acting_for_patient_id=patient_id)  # type: ignore[typeddict-item]
