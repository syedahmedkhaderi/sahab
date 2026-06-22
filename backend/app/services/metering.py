"""Metering service — per-minute credit deduction for active sessions.

Called by the worker (APScheduler) every 60 seconds.
Gracefully stops sessions whose balance reaches zero.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Rate, ResourceType, Session, SessionState
from app.services import credits as credits_svc
from app.services.jupyterhub import JupyterHubClient

logger = logging.getLogger(__name__)


async def _get_rate(resource_type: str, db: AsyncSession, settings: Settings) -> float:
    result = await db.execute(select(Rate).where(Rate.resource_type == resource_type))
    rate = result.scalar_one_or_none()
    if rate is not None:
        return float(rate.credits_per_minute)
    # Fall back to env defaults
    if resource_type == ResourceType.l4_gpu:
        return settings.credits_per_minute_l4
    return settings.credits_per_minute_cpu


async def meter_active_sessions(
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    hub: JupyterHubClient,
) -> None:
    """
    Deduct credits for all currently running sessions.

    For each running session:
      1. Compute minutes elapsed since last_metered_at.
      2. Look up the rate for the session's resource_type.
      3. Write a debit ledger entry.
      4. If balance hits zero or below, trigger graceful stop.
    """
    now = datetime.now(tz=timezone.utc)

    result = await db.execute(
        select(Session).where(Session.state == SessionState.running)
    )
    sessions = list(result.scalars().all())

    for session in sessions:
        if session.last_metered_at is None:
            # First tick — set the baseline without charging
            session.last_metered_at = now
            db.add(session)
            continue

        elapsed_minutes = (now - session.last_metered_at).total_seconds() / 60.0
        if elapsed_minutes < 0.5:
            # Not enough time has passed; skip to avoid micro-charges
            continue

        rate = await _get_rate(session.resource_type, db, settings)
        charge = elapsed_minutes * rate

        if charge <= 0:
            # CPU sessions with 0.0 rate — still update metered timestamp
            session.last_metered_at = now
            db.add(session)
            continue

        # Check current balance before debiting
        balance = await credits_svc.get_balance(session.user_id, db)
        if balance <= 0:
            logger.info(
                "Session %s: balance exhausted (%.2f), triggering stop", session.id, balance
            )
            await _stop_session_for_exhaustion(session, db, redis, settings, hub)
            continue

        # Debit (cap to available balance to avoid going deeply negative)
        actual_charge = min(charge, balance)
        entry = await credits_svc.debit_credits(
            db=db,
            user_id=session.user_id,
            amount=actual_charge,
            reason="metering",
            session_id=session.id,
        )

        session.last_metered_at = now
        db.add(session)

        logger.debug(
            "Metered session %s: -%.4f credits (rate=%.4f, minutes=%.2f), balance_after=%.4f",
            session.id,
            actual_charge,
            rate,
            elapsed_minutes,
            entry.balance_after,
        )

        if float(entry.balance_after) <= 0:
            logger.info(
                "Session %s: balance reached zero after metering, triggering stop", session.id
            )
            await _stop_session_for_exhaustion(session, db, redis, settings, hub)

    await db.commit()


async def _stop_session_for_exhaustion(
    session: Session,
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    hub: JupyterHubClient,
) -> None:
    """Gracefully stop a session because the user ran out of credits."""
    from app.services import sessions as sessions_svc  # noqa: PLC0415

    try:
        await sessions_svc.stop_session(
            db=db,
            redis=redis,
            session=session,
            settings=settings,
            hub=hub,
        )
    except Exception as exc:
        logger.error("Error stopping exhausted session %s: %s", session.id, exc)
