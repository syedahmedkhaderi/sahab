"""Credits and usage endpoints (user-facing)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import CreditLedger, ResourceType, Session, SessionState, User
from app.schemas import LedgerEntryOut, UsageSummary
from app.security import get_current_user
from app.services import credits as credits_svc

router = APIRouter(tags=["credits"])


@router.get("/credits/ledger", response_model=list[LedgerEntryOut])
async def get_ledger(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> list[CreditLedger]:
    """Return the authenticated user's ledger entries, newest first."""
    return await credits_svc.get_ledger(current_user.id, db, limit=limit, offset=offset)


@router.get("/usage", response_model=UsageSummary)
async def get_usage(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> UsageSummary:
    """Return usage summary for the authenticated user."""
    sessions_result = await db.execute(
        select(Session).where(Session.user_id == current_user.id)
    )
    all_sessions = list(sessions_result.scalars().all())

    total_sessions = len(all_sessions)
    total_gpu_minutes: float = 0.0
    total_cpu_minutes: float = 0.0

    for s in all_sessions:
        if s.started_at and s.ended_at:
            minutes = (s.ended_at - s.started_at).total_seconds() / 60.0
            if s.resource_type == ResourceType.l4_gpu:
                total_gpu_minutes += minutes
            else:
                total_cpu_minutes += minutes

    # Total credits used = sum of negative ledger entries
    credits_result = await db.execute(
        select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
            CreditLedger.user_id == current_user.id,
            CreditLedger.delta < 0,
        )
    )
    total_credits_used = abs(float(credits_result.scalar_one()))

    return UsageSummary(
        total_sessions=total_sessions,
        total_gpu_minutes=round(total_gpu_minutes, 2),
        total_cpu_minutes=round(total_cpu_minutes, 2),
        total_credits_used=round(total_credits_used, 4),
    )
