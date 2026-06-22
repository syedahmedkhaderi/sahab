"""Catalog endpoints: images and rates."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Image, Rate, User
from app.schemas import ImageOut, RateOut
from app.security import get_current_user

router = APIRouter(tags=["catalog"])


@router.get("/images", response_model=list[ImageOut])
async def list_images(
    _: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[Image]:
    """Return all enabled workspace images."""
    result = await db.execute(
        select(Image).where(Image.enabled.is_(True)).order_by(Image.name)
    )
    return list(result.scalars().all())


@router.get("/rates", response_model=list[RateOut])
async def list_rates(
    _: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[Rate]:
    """Return current pricing rates."""
    result = await db.execute(select(Rate).order_by(Rate.resource_type))
    return list(result.scalars().all())
