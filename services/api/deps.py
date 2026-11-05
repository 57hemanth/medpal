"""Request dependencies: who is calling (AuthContext)."""

from fastapi import HTTPException, Request, status

from services.platform.auth import AuthContext
from services.platform.config import get_settings
from services.platform.identity import IdentityError, resolve_identity


async def auth_ctx(request: Request) -> AuthContext:
    """OIDC bearer token in production; X-Dev-* headers in development only (refused in prod)."""
    try:
        return resolve_identity(request.headers, get_settings())
    except IdentityError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
