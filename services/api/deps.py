"""Request dependencies: who is calling (AuthContext)."""

from fastapi import Header, HTTPException, status

from services.platform.auth import ROLES, AuthContext
from services.platform.config import get_settings


async def auth_ctx(
    x_dev_user_id: str | None = Header(default=None),
    x_dev_role: str | None = Header(default=None),
    x_dev_patient_id: str | None = Header(default=None),
) -> AuthContext:
    """Dev mode trusts X-Dev-* headers so the stack runs before OIDC login (Keycloak) is added.
    Settings refuse auth_mode=dev in prod, and OIDC mode fails closed until it is implemented."""
    settings = get_settings()
    if settings.auth_mode != "dev":
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "OIDC authentication is not implemented yet")
    if not x_dev_user_id or x_dev_role not in ROLES:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid dev identity headers")
    acting_for = x_dev_patient_id if x_dev_role == "patient" else None
    if x_dev_role == "patient" and not acting_for:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "patient identity needs X-Dev-Patient-Id")
    return AuthContext(user_id=x_dev_user_id, role=x_dev_role, acting_for_patient_id=acting_for)  # type: ignore[typeddict-item]
