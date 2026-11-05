"""Who is calling, resolved the same way for every entry point (REST API and MCP tool server).

* oidc mode: a signed bearer token, verified against the issuer's keys. The header is only a carrier;
  the identity comes from the verified signature, never from the header text itself.
* dev mode: X-Dev-* headers, for local development only. Settings refuse dev mode in production.
"""

from collections.abc import Mapping

from .auth import ROLES, AuthContext
from .config import Settings
from .oidc import OidcError, verify_token


class IdentityError(ValueError):
    pass


def resolve_identity(headers: Mapping[str, str] | None, settings: Settings) -> AuthContext:
    h = {k.lower(): v for k, v in (headers or {}).items()}
    if settings.auth_mode != "dev":
        authorization = h.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise IdentityError("missing bearer token")
        try:
            return verify_token(authorization.removeprefix("Bearer ").strip(), settings)
        except OidcError as exc:
            raise IdentityError(str(exc)) from exc
    user, role, patient = h.get("x-dev-user-id"), h.get("x-dev-role"), h.get("x-dev-patient-id")
    if not user or role not in ROLES:
        raise IdentityError("missing or invalid dev identity headers")
    if role == "patient" and not patient:
        raise IdentityError("patient identity needs X-Dev-Patient-Id")
    return AuthContext(user_id=user, role=role, acting_for_patient_id=patient if role == "patient" else None)  # type: ignore[typeddict-item]
