"""Prometheus scrape endpoint.

Exposes aggregate platform gauges in Prometheus text exposition format at
``/api/metrics`` so the Prometheus service (see ``infra/prometheus/prometheus.yml``)
and the Grafana dashboard can read ``sahab_queue_depth`` and
``sahab_credits_burned_total`` among others.

Unauthenticated by design: it returns only platform-wide aggregates (no
per-user data). In production it should still be reachable only from inside the
``sahab-network`` (Prometheus), not published through Traefik to the internet.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import (
    CreditLedger,
    GpuInventory,
    GpuStatus,
    LedgerReason,
    Session,
    SessionState,
    User,
)

router = APIRouter(tags=["metrics"])


def _line(name: str, value: float, help_text: str, mtype: str) -> str:
    return f"# HELP {name} {help_text}\n# TYPE {name} {mtype}\n{name} {value}\n"


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(db: AsyncSession = Depends(get_db)) -> Response:
    # Queue depth: sessions waiting for a GPU.
    queue_depth = (
        await db.execute(
            select(func.count()).select_from(Session).where(Session.state == SessionState.queued.value)
        )
    ).scalar_one()

    # Active (running) sessions.
    active_sessions = (
        await db.execute(
            select(func.count()).select_from(Session).where(Session.state == SessionState.running.value)
        )
    ).scalar_one()

    # Credits burned (cumulative): metering debits are negative deltas; report the
    # absolute total so the dashboard can rate() it into credits/hour.
    burned = (
        await db.execute(
            select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
                CreditLedger.reason == LedgerReason.metering.value
            )
        )
    ).scalar_one()
    credits_burned_total = abs(float(burned or 0))

    # GPU inventory by status.
    gpu_rows = (
        await db.execute(select(GpuInventory.status, func.count()).group_by(GpuInventory.status))
    ).all()
    gpu_counts = {status: count for status, count in gpu_rows}
    gpus_total = sum(gpu_counts.values())
    gpus_leased = gpu_counts.get(GpuStatus.leased.value, 0)
    gpus_free = gpu_counts.get(GpuStatus.free.value, 0)
    gpus_disabled = gpu_counts.get(GpuStatus.disabled.value, 0)

    users_total = (await db.execute(select(func.count()).select_from(User))).scalar_one()

    body = "".join([
        _line("sahab_queue_depth", queue_depth, "Sessions waiting in the GPU queue", "gauge"),
        _line("sahab_active_sessions", active_sessions, "Currently running sessions", "gauge"),
        _line("sahab_credits_burned_total", credits_burned_total,
              "Cumulative credits debited by metering", "counter"),
        _line("sahab_gpus_total", gpus_total, "Total GPUs in inventory", "gauge"),
        _line("sahab_gpus_leased", gpus_leased, "GPUs currently leased", "gauge"),
        _line("sahab_gpus_free", gpus_free, "GPUs currently free", "gauge"),
        _line("sahab_gpus_disabled", gpus_disabled, "GPUs currently disabled", "gauge"),
        _line("sahab_users_total", users_total, "Total registered users", "gauge"),
    ])
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
