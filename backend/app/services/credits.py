"""Credit ledger service — append-only writes, balance recompute, grant/debit."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CreditLedger, LedgerReason, User


async def get_balance(user_id: str, db: AsyncSession) -> float:
    """Recompute the user's balance from the ledger (source of truth)."""
    result = await db.execute(
        select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
            CreditLedger.user_id == user_id
        )
    )
    return float(result.scalar_one())


async def _append_entry(
    *,
    db: AsyncSession,
    user_id: str,
    delta: float,
    reason: str,
    session_id: str | None,
) -> CreditLedger:
    """
    Write one ledger row and update the cached balance on the user row.

    This is the only function that should ever mutate credit_balance.
    """
    # Recompute balance from ledger to ensure correctness
    current_balance = await get_balance(user_id, db)
    new_balance = current_balance + delta

    entry = CreditLedger(
        user_id=user_id,
        delta=delta,
        reason=reason,
        session_id=session_id,
        balance_after=new_balance,
    )
    db.add(entry)

    # Update the cached balance on the user row
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(credit_balance=new_balance)
    )

    await db.flush()
    return entry


async def grant_credits(
    *,
    db: AsyncSession,
    user_id: str,
    amount: float,
    reason: str = LedgerReason.grant,
    session_id: str | None = None,
) -> CreditLedger:
    """Grant credits to a user (positive delta)."""
    if amount <= 0:
        raise ValueError("Grant amount must be positive")
    return await _append_entry(
        db=db,
        user_id=user_id,
        delta=amount,
        reason=reason,
        session_id=session_id,
    )


async def debit_credits(
    *,
    db: AsyncSession,
    user_id: str,
    amount: float,
    reason: str = LedgerReason.metering,
    session_id: str | None = None,
) -> CreditLedger:
    """Debit credits from a user (negative delta)."""
    if amount <= 0:
        raise ValueError("Debit amount must be positive")
    return await _append_entry(
        db=db,
        user_id=user_id,
        delta=-amount,
        reason=reason,
        session_id=session_id,
    )


async def get_ledger(
    user_id: str,
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
) -> list[CreditLedger]:
    """Return ledger entries for a user, newest first."""
    result = await db.execute(
        select(CreditLedger)
        .where(CreditLedger.user_id == user_id)
        .order_by(CreditLedger.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
