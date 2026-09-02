"""Live GPU utilisation probe.

The `gpu_inventory.status` column only records what Sahab itself has leased. It
knows nothing about work started outside the platform — a researcher's job on
the host, say — so a GPU can read as free in the DB while it is in fact busy.

The DCGM exporter already scrapes the driver and labels every sample with the
same UUID the scheduler leases, so a plain HTTP GET over the Docker network is
enough to tell the difference. No nvidia-smi, no NVIDIA runtime and no extra
privilege in the backend container.

Every failure path here returns None. The probe is an optimisation on top of the
DB, never a new way for a launch to fail.
"""

from __future__ import annotations

import logging
import re
import time

import httpx

logger = logging.getLogger(__name__)

# One sample line, e.g.
#   DCGM_FI_DEV_FB_USED{gpu="0",UUID="GPU-7732…",device="nvidia0",…} 9326
_SAMPLE_RE = re.compile(
    r'^(?P<metric>DCGM_FI_DEV_GPU_UTIL|DCGM_FI_DEV_FB_USED)\{(?P<labels>[^}]*)\}\s+(?P<value>[0-9.eE+-]+)\s*$'
)
_UUID_RE = re.compile(r'UUID="(?P<uuid>[^"]+)"')

_CACHE_TTL_SECONDS = 5.0
_REQUEST_TIMEOUT_SECONDS = 2.0

# Module-level memo, keyed by exporter URL: url -> (expires_at, readings).
# Keying by URL matters once there is more than one machine: a single shared slot
# would hand the second node's scheduler the first node's numbers and place work
# on a GPU it believes is idle.
_cache: dict[str, tuple[float, dict[str, "GpuReading"]]] = {}


class GpuReading:
    """A single GPU's live utilisation, as reported by DCGM."""

    __slots__ = ("util_pct", "used_mb")

    def __init__(self, util_pct: float, used_mb: float) -> None:
        self.util_pct = util_pct
        self.used_mb = used_mb

    def is_busy(self, busy_vram_mb: float, busy_util_pct: float) -> bool:
        return self.used_mb > busy_vram_mb or self.util_pct > busy_util_pct

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"GpuReading(util_pct={self.util_pct}, used_mb={self.used_mb})"


def parse_dcgm_metrics(text: str) -> dict[str, GpuReading]:
    """Parse a DCGM exporter scrape into {gpu_uuid: GpuReading}."""
    util: dict[str, float] = {}
    used: dict[str, float] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE_RE.match(line)
        if match is None:
            continue
        uuid_match = _UUID_RE.search(match.group("labels"))
        if uuid_match is None:
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        target = util if match.group("metric") == "DCGM_FI_DEV_GPU_UTIL" else used
        target[uuid_match.group("uuid")] = value

    # Only report a GPU we have both numbers for; a half-read is not a signal
    # strong enough to refuse someone a GPU on.
    return {
        uuid: GpuReading(util_pct=util[uuid], used_mb=used[uuid])
        for uuid in util.keys() & used.keys()
    }


async def get_gpu_readings(metrics_url: str) -> dict[str, GpuReading] | None:
    """
    Fetch live per-GPU utilisation, memoised for a few seconds.

    Returns None if the exporter is unreachable, slow, or unparseable — callers
    must fall back to the DB-status-only path in that case.
    """
    now = time.monotonic()
    cached = _cache.get(metrics_url)
    if cached is not None and cached[0] > now:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(metrics_url)
            response.raise_for_status()
            readings = parse_dcgm_metrics(response.text)
    except Exception as exc:
        logger.warning(
            "GPU probe at %s unavailable (%s); falling back to DB status", metrics_url, exc
        )
        return None

    if not readings:
        logger.warning(
            "GPU probe at %s returned no usable samples; falling back to DB status", metrics_url
        )
        return None

    _cache[metrics_url] = (now + _CACHE_TTL_SECONDS, readings)
    return readings


def reset_cache() -> None:
    """Drop the memoised readings. Used by tests."""
    _cache.clear()
