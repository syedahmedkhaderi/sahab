"""Current-user profile endpoints."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User
from app.schemas import ProfileUpdateRequest, UserOut
from app.security import get_current_user, hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=UserOut)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Return the authenticated user's profile."""
    return current_user


@router.patch("", response_model=UserOut)
async def update_me(
    body: ProfileUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Change your own display name or password.

    The settings page has offered this since it was written; the endpoint behind
    it did not exist, so every save returned 405. Scope is deliberately narrow:
    a user can rename themselves and set a new password, and nothing else.

    Changing the password does not invalidate existing sessions. The tokens are
    stateless JWTs with no server-side record to revoke, so that would need a
    token version column — worth doing, but a separate change from making the
    button work at all.
    """
    if body.full_name is None and body.password is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nothing to change.",
        )

    if body.full_name is not None:
        current_user.full_name = body.full_name.strip()
    if body.password is not None:
        current_user.password_hash = hash_password(body.password)
        logger.info("User %s changed their password", current_user.id)

    db.add(current_user)
    await db.flush()
    await db.refresh(current_user)
    return current_user
