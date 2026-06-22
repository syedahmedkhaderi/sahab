"""Tests: credit grant, debit, balance calculation."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services.credits import debit_credits, get_balance, get_ledger, grant_credits


@pytest.mark.asyncio
async def test_initial_balance_is_zero(db_session: AsyncSession) -> None:
    """A user with no ledger entries has zero balance."""
    from app.security import hash_password

    user = User(
        email="new@udst.edu.qa",
        full_name="New",
        role="student",
        status="active",
        password_hash=hash_password("pass12345678"),
        credit_balance=0,
    )
    db_session.add(user)
    await db_session.flush()

    balance = await get_balance(user.id, db_session)
    assert balance == 0.0


@pytest.mark.asyncio
async def test_grant_increases_balance(active_user: User, db_session: AsyncSession) -> None:
    """Granting credits increases the ledger sum."""
    before = await get_balance(active_user.id, db_session)
    await grant_credits(db=db_session, user_id=active_user.id, amount=100)
    after = await get_balance(active_user.id, db_session)
    assert after == pytest.approx(before + 100, rel=1e-4)


@pytest.mark.asyncio
async def test_debit_decreases_balance(active_user: User, db_session: AsyncSession) -> None:
    """Debiting credits decreases the balance."""
    before = await get_balance(active_user.id, db_session)
    await debit_credits(db=db_session, user_id=active_user.id, amount=50)
    after = await get_balance(active_user.id, db_session)
    assert after == pytest.approx(before - 50, rel=1e-4)


@pytest.mark.asyncio
async def test_ledger_is_append_only(active_user: User, db_session: AsyncSession) -> None:
    """Ledger entries are immutable; each operation adds a new row."""
    before_entries = await get_ledger(active_user.id, db_session)
    await grant_credits(db=db_session, user_id=active_user.id, amount=10)
    await debit_credits(db=db_session, user_id=active_user.id, amount=5)
    after_entries = await get_ledger(active_user.id, db_session)

    assert len(after_entries) == len(before_entries) + 2


@pytest.mark.asyncio
async def test_balance_after_tracks_correctly(active_user: User, db_session: AsyncSession) -> None:
    """Each ledger entry should record the running balance after the operation."""
    entry1 = await grant_credits(db=db_session, user_id=active_user.id, amount=200)
    entry2 = await debit_credits(db=db_session, user_id=active_user.id, amount=75)

    assert float(entry2.balance_after) == pytest.approx(float(entry1.balance_after) - 75, rel=1e-4)


@pytest.mark.asyncio
async def test_grant_amount_must_be_positive(active_user: User, db_session: AsyncSession) -> None:
    """Granting zero or negative credits should raise ValueError."""
    with pytest.raises(ValueError):
        await grant_credits(db=db_session, user_id=active_user.id, amount=0)
    with pytest.raises(ValueError):
        await grant_credits(db=db_session, user_id=active_user.id, amount=-10)


@pytest.mark.asyncio
async def test_debit_amount_must_be_positive(active_user: User, db_session: AsyncSession) -> None:
    """Debiting zero or negative credits should raise ValueError."""
    with pytest.raises(ValueError):
        await debit_credits(db=db_session, user_id=active_user.id, amount=0)
    with pytest.raises(ValueError):
        await debit_credits(db=db_session, user_id=active_user.id, amount=-5)
