"""Current authenticated principal."""

from typing import Annotated

from fastapi import APIRouter, Depends

from services.api.deps import auth_ctx
from services.platform.auth import AuthContext

router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/me")
async def me(auth: Annotated[AuthContext, Depends(auth_ctx)]) -> AuthContext:
    return auth
