"""Current-user profile endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.models import User
from app.schemas import UserOut
from app.security import get_current_user

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserOut)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Return the authenticated user's profile."""
    return current_user
