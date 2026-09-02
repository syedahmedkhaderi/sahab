"""Node registry: enrollment, reachability, and the files the spawner reads.

A "node" is a machine that can run workspace containers. The manager — the VM
running the control plane — is node number one and reaches its own containers
through the local Docker socket; every other node is reached over a mutually
authenticated Docker API on port 2376.

Two artefacts are written to disk here rather than kept only in the database,
because the two things that need them cannot query Postgres:

* ``nodes.json``  — JupyterHub's spawner reads it to learn a node's address and
  certificate paths, so adding a machine never requires restarting the hub.
* Prometheus ``file_sd`` targets — so a new machine's GPU metrics are scraped
  without editing prometheus.yml by hand.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import (
    EnrollmentStatus,
    GpuInventory,
    GpuStatus,
    Node,
    NodeEnrollment,
    NodeStatus,
)
from app.services import node_certs

logger = logging.getLogger(__name__)

ENROLL_TOKEN_TTL_HOURS = 24
DOCKER_PING_TIMEOUT_SECONDS = 5.0

# Ports a worker node publishes for the manager to scrape.
DCGM_PORT = 9400
NODE_EXPORTER_PORT = 9100
CADVISOR_PORT = 8080


class NodeError(Exception):
    """Something about a node's configuration or state blocks the operation."""


# ---------------------------------------------------------------------------
# Identity of the manager
# ---------------------------------------------------------------------------

def manager_node_name(settings: Settings | None = None) -> str:
    """The manager's node name.

    Resolved the same way in the app and in migration 0003 so the seeded row and
    the running app always agree on which row is "this machine".
    """
    settings = settings or get_settings()
    return settings.manager_node_name or os.environ.get("MANAGER_NODE_NAME") or socket.gethostname()


async def ensure_manager_node(db: AsyncSession, settings: Settings) -> Node:
    """Make sure the control-plane VM has a node row. Idempotent.

    Called at startup because a database built by ``create_all`` (which is what a
    fresh bootstrap does) has the tables but none of the seed rows a migration
    would have inserted.
    """
    name = manager_node_name(settings)
    result = await db.execute(select(Node).where(Node.is_manager.is_(True)))
    node = result.scalars().first()

    if node is None:
        node = Node(
            name=name,
            display_name="Control plane",
            address="",
            is_manager=True,
            status=NodeStatus.ready,
            enrolled_at=datetime.now(tz=timezone.utc),
            last_seen_at=datetime.now(tz=timezone.utc),
        )
        db.add(node)
        await db.flush()
        logger.info("Seeded manager node %s", name)
    elif node.name != name:
        # The host was renamed. Correct the row rather than adding a second
        # manager, which would split the inventory between two half-real nodes.
        logger.info("Manager node renamed: %s -> %s", node.name, name)
        node.name = name
        await db.flush()

    return node


# ---------------------------------------------------------------------------
# Enrollment tokens
# ---------------------------------------------------------------------------

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_enrollment(
    db: AsyncSession, node: Node, actor_id: str | None
) -> tuple[str, NodeEnrollment]:
    """Issue a one-time join token. Returns (plaintext token, row).

    The plaintext is shown to the admin once and never stored — only its SHA-256
    is kept, so a database dump does not hand over the ability to join machines
    to the cluster.
    """
    token = secrets.token_urlsafe(32)
    enrollment = NodeEnrollment(
        node_id=node.id,
        token_hash=_hash_token(token),
        status=EnrollmentStatus.issued,
        log="",
        expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=ENROLL_TOKEN_TTL_HOURS),
        created_by=actor_id,
    )
    db.add(enrollment)
    await db.flush()
    return token, enrollment


async def resolve_enrollment(db: AsyncSession, token: str) -> tuple[NodeEnrollment, Node]:
    """Look up a live enrollment by its plaintext token.

    Raises NodeError for every rejection with the same shape of message: a token
    that is unknown, spent or expired should not be distinguishable to a caller
    guessing at tokens.
    """
    result = await db.execute(
        select(NodeEnrollment).where(NodeEnrollment.token_hash == _hash_token(token))
    )
    enrollment = result.scalar_one_or_none()
    if enrollment is None:
        raise NodeError("Invalid or expired enrollment token")

    expires_at = enrollment.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(tz=timezone.utc):
        enrollment.status = EnrollmentStatus.expired
        await db.flush()
        raise NodeError("Invalid or expired enrollment token")

    if enrollment.status == EnrollmentStatus.completed:
        raise NodeError("Invalid or expired enrollment token")

    node = await db.get(Node, enrollment.node_id)
    if node is None:
        raise NodeError("Invalid or expired enrollment token")

    return enrollment, node


async def append_log(db: AsyncSession, enrollment: NodeEnrollment, text: str) -> None:
    """Append to an enrollment's install log, keeping only the recent tail.

    The log is polled by the admin UI; an unbounded column would let a chatty
    apt-get turn one bad install into a multi-megabyte row.
    """
    combined = (enrollment.log or "") + text
    max_chars = 200_000
    if len(combined) > max_chars:
        combined = "…(earlier output trimmed)…\n" + combined[-max_chars:]
    enrollment.log = combined
    await db.flush()


async def stash_reported_gpus(
    db: AsyncSession, enrollment: NodeEnrollment, gpus: list[dict]
) -> None:
    """Remember what a machine said it has, without acting on it yet."""
    enrollment.reported_gpus = json.dumps(gpus)
    await db.flush()


async def take_reported_gpus(db: AsyncSession, enrollment: NodeEnrollment) -> list[dict]:
    """Read back the stashed GPU list. Returns [] if the machine never sent one."""
    raw = enrollment.reported_gpus
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Enrollment %s has an unreadable GPU list", enrollment.id)
        return []
    return parsed if isinstance(parsed, list) else []


def join_command(token: str, settings: Settings) -> str:
    """The one line an admin pastes on a new GPU server."""
    base = settings.enroll_base_url
    repo = settings.sahab_repo_url.removesuffix(".git").replace(
        "https://github.com/", "https://raw.githubusercontent.com/"
    )
    script = f"{repo}/{settings.sahab_branch}/scripts/join_node.sh"
    return f"curl -fsSL {script} | sudo bash -s -- --server {base} --token {token}"


# ---------------------------------------------------------------------------
# Talking to a node's Docker API
# ---------------------------------------------------------------------------

def docker_base_url(node: Node) -> str:
    """HTTPS base URL for a node's Docker API. Empty for the local socket."""
    if node.is_local:
        return ""
    return f"https://{node.address}:{node.docker_port}"


async def ping_node(node: Node) -> tuple[bool, str | None]:
    """Check a node's Docker API. Returns (reachable, docker version or error).

    The manager is reported reachable without a probe: its containers go through
    the local socket, and if that were broken the control plane would not be
    running to ask the question.
    """
    if node.is_local:
        return True, None

    node_certs.ensure_client_cert()  # guarantees the files below exist
    try:
        async with httpx.AsyncClient(
            verify=str(node_certs.ca_cert_path()),
            cert=(str(node_certs.client_cert_path()), str(node_certs.client_key_path())),
            timeout=DOCKER_PING_TIMEOUT_SECONDS,
        ) as client:
            resp = await client.get(f"{docker_base_url(node)}/version")
            resp.raise_for_status()
            return True, str(resp.json().get("Version") or "")
    except Exception as exc:  # noqa: BLE001 — every failure means "not reachable"
        logger.info("Node %s unreachable: %s", node.name, exc)
        return False, str(exc)


async def record_health(
    db: AsyncSession, node: Node, reachable: bool, detail: str | None
) -> None:
    """Fold a probe result into a node's status.

    Deliberately conservative in three directions:

    * A machine that has never enrolled is left alone entirely. Calling it
      'unreachable' would claim a state it was never in — it is not broken, it
      just has not been set up yet — and the reverse would be worse: a stray
      Docker daemon answering on that address could carry it to 'ready' without
      ever having enrolled. Enrollment is the only way into the pool.
    * A node an admin has taken out by hand ('draining', 'disabled') keeps that
      status. A reachability probe is not a reason to put a machine back into
      service that somebody deliberately removed.
    * A node that comes back reachable returns to 'ready', and its GPUs are
      re-enabled by the health job, not here — that decision needs to look at
      open leases, which is the job's business.
    """
    now = datetime.now(tz=timezone.utc)

    if node.enrolled_at is None:
        return

    if reachable:
        node.last_seen_at = now
        if detail:
            node.docker_version = detail[:64]
        node.unreachable_since = None
        if node.status == NodeStatus.unreachable:
            logger.info("Node %s is reachable again", node.name)
            node.status = NodeStatus.ready
    else:
        if node.status in (NodeStatus.draining, NodeStatus.disabled):
            return
        if node.status != NodeStatus.unreachable:
            logger.warning("Node %s stopped answering: %s", node.name, detail)
            node.status = NodeStatus.unreachable
            node.unreachable_since = now

    await db.flush()


# ---------------------------------------------------------------------------
# GPU inventory for a node
# ---------------------------------------------------------------------------

async def sync_node_gpus(
    db: AsyncSession, node: Node, gpus: list[dict]
) -> tuple[int, int]:
    """Reconcile a node's reported GPUs with the inventory.

    Returns (added, updated). A GPU that has vanished from the node is *not*
    deleted — an inventory row can be referenced by lease history, and a GPU
    missing from one report is far more often a driver hiccup than a removed
    card. Those rows are marked disabled instead, and come back on their own the
    next time the node reports them.
    """
    added = updated = 0
    reported: set[str] = set()

    for entry in gpus:
        gpu_uuid = str(entry.get("gpu_uuid") or "").strip()
        if not gpu_uuid:
            continue
        reported.add(gpu_uuid)
        model = str(entry.get("model") or "Unknown GPU")[:128]
        try:
            vram_mb = int(entry.get("vram_mb") or 0)
        except (TypeError, ValueError):
            vram_mb = 0

        existing = (
            await db.execute(select(GpuInventory).where(GpuInventory.gpu_uuid == gpu_uuid))
        ).scalar_one_or_none()

        if existing is None:
            db.add(
                GpuInventory(
                    gpu_uuid=gpu_uuid,
                    node_id=node.id,
                    model=model,
                    vram_mb=vram_mb,
                    status=GpuStatus.free,
                )
            )
            added += 1
        else:
            existing.node_id = node.id
            existing.model = model
            existing.vram_mb = vram_mb
            # Never yank a GPU out from under a running session.
            if existing.status == GpuStatus.disabled:
                existing.status = GpuStatus.free
            updated += 1

    # An empty report means nvidia-smi failed, not that someone unscrewed every
    # card — so only sweep when the node actually told us about some GPUs.
    if reported:
        stale = (
            await db.execute(
                select(GpuInventory).where(
                    GpuInventory.node_id == node.id,
                    GpuInventory.gpu_uuid.notin_(reported),
                )
            )
        ).scalars().all()
        for gpu in stale:
            if gpu.status == GpuStatus.free:
                logger.warning(
                    "GPU %s no longer reported by node %s; disabling", gpu.gpu_uuid, node.name
                )
                gpu.status = GpuStatus.disabled

    await db.flush()
    return added, updated


# ---------------------------------------------------------------------------
# Files the hub and Prometheus read
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, payload: str) -> None:
    """Write through a temp file so a reader never sees a half-written map."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload)
    tmp.replace(path)


async def publish_node_map(db: AsyncSession, settings: Settings) -> None:
    """Rewrite nodes.json (for the spawner) and the Prometheus target list.

    Called after every change to the node set. Failures are logged, not raised:
    a monitoring file that could not be written must not fail an admin's request
    or, worse, an enrollment that otherwise succeeded.
    """
    nodes = (await db.execute(select(Node).order_by(Node.name))).scalars().all()

    node_map = {
        "network": settings.docker_network_name,
        "ca_cert": str(node_certs.ca_cert_path()),
        "client_cert": str(node_certs.client_cert_path()),
        "client_key": str(node_certs.client_key_path()),
        "nodes": {
            node.name: {
                "address": node.address,
                "docker_port": node.docker_port,
                "local": node.is_local,
                "status": node.status,
            }
            for node in nodes
        },
    }
    try:
        _atomic_write(Path(settings.node_map_path), json.dumps(node_map, indent=2) + "\n")
    except OSError as exc:
        logger.error("Could not write the node map at %s: %s", settings.node_map_path, exc)

    targets = []
    for node in nodes:
        if node.is_local or not node.address:
            continue
        targets.append(
            {
                "targets": [
                    f"{node.address}:{DCGM_PORT}",
                    f"{node.address}:{NODE_EXPORTER_PORT}",
                    f"{node.address}:{CADVISOR_PORT}",
                ],
                "labels": {"sahab_node": node.name},
            }
        )
    try:
        _atomic_write(
            Path(settings.prometheus_targets_path), json.dumps(targets, indent=2) + "\n"
        )
    except OSError as exc:
        logger.error(
            "Could not write Prometheus targets at %s: %s", settings.prometheus_targets_path, exc
        )


def default_metrics_url(address: str) -> str:
    return f"http://{address}:{DCGM_PORT}/metrics"
