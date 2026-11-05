"""Who is calling, resolved the same way for every entry point (REST API and MCP tool server).

* otp mode: the signed session cookie set at mobile sign-in (services/platform/signin.py).
* oidc mode: a signed bearer token, verified against the issuer's keys. The header is only a carrier;
  the identity comes from the verified signature, never from the header text itself.
* dev mode: a signed-in session cookie if there is one, else X-Dev-* headers (tests and tooling).
  Settings refuse dev mode in production.
"""

from collections.abc import Mapping
from http.cookies import CookieError, SimpleCookie

from .auth import ROLES, AuthContext
from .config import Settings
from .oidc import OidcError, verify_token


class IdentityError(ValueError):
    pass


def _session_cookie(h: Mapping[str, str]) -> str | None:
    from .signin import COOKIE

    raw = h.get("cookie")
    if not raw:
        return None
    try:
        jar = SimpleCookie(raw)
    except CookieError:
        return None
    morsel = jar.get(COOKIE)
    return morsel.value if morsel else None


def resolve_identity(headers: Mapping[str, str] | None, settings: Settings) -> AuthContext:
    from .signin import SignInError, auth_from_session

    h = {k.lower(): v for k, v in (headers or {}).items()}
    if settings.auth_mode in ("otp", "dev"):
        token = _session_cookie(h)
        if token:
            try:
                return auth_from_session(token, settings)
            except SignInError as exc:
                raise IdentityError(str(exc)) from exc
        if settings.auth_mode == "otp":
            raise IdentityError("not signed in")
    if settings.auth_mode == "oidc":
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
