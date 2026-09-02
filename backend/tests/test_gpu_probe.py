"""Tests: live GPU utilisation probe and the busy-GPU scheduling it drives."""

from __future__ import annotations

import fakeredis.aioredis as fakeredis
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GpuInventory, GpuStatus, ResourceType, Session, SessionState, User
from app.services import gpu_probe
from app.services import scheduler as scheduler_svc

# A realistic slice of a DCGM exporter scrape: one busy card, one idle.
SCRAPE = """
# HELP DCGM_FI_DEV_GPU_UTIL GPU utilization (in %).
# TYPE DCGM_FI_DEV_GPU_UTIL gauge
DCGM_FI_DEV_GPU_UTIL{gpu="0",UUID="GPU-busy",device="nvidia0",modelName="NVIDIA L4"} 85
DCGM_FI_DEV_GPU_UTIL{gpu="1",UUID="GPU-idle",device="nvidia1",modelName="NVIDIA L4"} 0
# HELP DCGM_FI_DEV_FB_USED Framebuffer memory used (in MiB).
# TYPE DCGM_FI_DEV_FB_USED gauge
DCGM_FI_DEV_FB_USED{gpu="0",UUID="GPU-busy",device="nvidia0",modelName="NVIDIA L4"} 9326
DCGM_FI_DEV_FB_USED{gpu="1",UUID="GPU-idle",device="nvidia1",modelName="NVIDIA L4"} 278
DCGM_FI_DEV_SM_CLOCK{gpu="0",UUID="GPU-busy",device="nvidia0"} 1200
"""


def test_parses_util_and_memory_per_uuid() -> None:
    readings = gpu_probe.parse_dcgm_metrics(SCRAPE)

    assert set(readings) == {"GPU-busy", "GPU-idle"}
    assert readings["GPU-busy"].util_pct == 85
    assert readings["GPU-busy"].used_mb == 9326
    assert readings["GPU-idle"].used_mb == 278


def test_ignores_comments_and_unrelated_metrics() -> None:
    readings = gpu_probe.parse_dcgm_metrics(SCRAPE)
    # SM_CLOCK is in the scrape but is not one of the two signals we act on.
    assert all(hasattr(r, "util_pct") and hasattr(r, "used_mb") for r in readings.values())


def test_a_gpu_missing_one_of_the_two_signals_is_not_reported() -> None:
    """Half a reading is not evidence strong enough to refuse someone a GPU."""
    partial = 'DCGM_FI_DEV_GPU_UTIL{UUID="GPU-only-util"} 10\n'
    assert gpu_probe.parse_dcgm_metrics(partial) == {}


def test_garbage_input_yields_nothing_rather_than_raising() -> None:
    assert gpu_probe.parse_dcgm_metrics("<html>502 Bad Gateway</html>") == {}


@pytest.mark.parametrize(
    ("util", "used_mb", "expected_busy"),
    [
        (0, 278, False),      # genuinely idle
        (0, 9326, True),      # memory held by another job, even at 0% util
        (85, 100, True),      # busy compute, little memory
        (30, 1024, False),    # exactly at both thresholds is not over them
    ],
)
def test_busy_thresholds(util: float, used_mb: float, expected_busy: bool) -> None:
    reading = gpu_probe.GpuReading(util_pct=util, used_mb=used_mb)
    assert reading.is_busy(busy_vram_mb=1024, busy_util_pct=30) is expected_busy


@pytest.mark.asyncio
async def test_scheduler_skips_the_busy_gpu(
    db_session: AsyncSession,
    active_user: User,
    gpu_inventory: list[GpuInventory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A GPU free in the DB but busy on the host must not be handed out."""
    redis = fakeredis.FakeRedis()
    gpus = sorted(g.gpu_uuid for g in gpu_inventory)
    busy, idle = gpus[0], gpus[1]

    async def fake_readings(_url: str):
        return {
            busy: gpu_probe.GpuReading(util_pct=90, used_mb=9000),
            idle: gpu_probe.GpuReading(util_pct=0, used_mb=200),
        }

    monkeypatch.setattr(gpu_probe, "get_gpu_readings", fake_readings)

    session = Session(
        user_id=active_user.id,
        resource_type=ResourceType.l4_gpu,
        state=SessionState.requested,
    )
    db_session.add(session)
    await db_session.flush()

    leased = await scheduler_svc.try_lease_gpu(session.id, db_session, redis)
    assert leased is not None
    assert leased.gpu_uuid == idle
    await redis.aclose()


@pytest.mark.asyncio
async def test_all_busy_raises_rather_than_queueing_silently(
    db_session: AsyncSession,
    active_user: User,
    gpu_inventory: list[GpuInventory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every free GPU busy is a different situation from an empty pool."""
    redis = fakeredis.FakeRedis()

    async def all_busy(_url: str):
        return {
            g.gpu_uuid: gpu_probe.GpuReading(util_pct=95, used_mb=9000)
            for g in gpu_inventory
        }

    monkeypatch.setattr(gpu_probe, "get_gpu_readings", all_busy)

    session = Session(
        user_id=active_user.id,
        resource_type=ResourceType.l4_gpu,
        state=SessionState.requested,
    )
    db_session.add(session)
    await db_session.flush()

    with pytest.raises(scheduler_svc.GpuBusyError):
        await scheduler_svc.try_lease_gpu(session.id, db_session, redis)

    # Nothing was leased on the way out.
    result = await db_session.execute(select(GpuInventory))
    assert all(g.status == GpuStatus.free for g in result.scalars().all())
    await redis.aclose()


@pytest.mark.asyncio
async def test_probe_failure_falls_back_to_db_status(
    db_session: AsyncSession,
    active_user: User,
    gpu_inventory: list[GpuInventory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A monitoring outage must not become a new way for launches to fail."""
    redis = fakeredis.FakeRedis()

    async def unavailable(_url: str):
        return None

    monkeypatch.setattr(gpu_probe, "get_gpu_readings", unavailable)

    session = Session(
        user_id=active_user.id,
        resource_type=ResourceType.l4_gpu,
        state=SessionState.requested,
    )
    db_session.add(session)
    await db_session.flush()

    leased = await scheduler_svc.try_lease_gpu(session.id, db_session, redis)
    assert leased is not None
    await redis.aclose()
