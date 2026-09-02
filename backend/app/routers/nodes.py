"""Enrollment endpoints — called by a machine joining the cluster, not by a browser.

These are the only endpoints in Sahab authenticated by a bearer token rather than
a user session, because a machine running the join script has no account. The
token is single-use, expires in 24 hours, and is stored only as a SHA-256 hash;
the same shape of trust k3s and Docker Swarm use for their own join tokens.

The response to /enroll carries real secrets (the swarm join token and the
machine's Docker server key), so this must be reached over HTTPS. In the normal
deployment it is: the only way in is through Cloudflare and Traefik.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import EnrollmentStatus, Node, NodeStatus
from app.schemas import (
    EnrollCompleteRequest,
    EnrollCompleteResponse,
    EnrollRequest,
    EnrollResponse,
)
from app.services import node_certs, nodes as nodes_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nodes", tags=["nodes"])


def _bad_token() -> HTTPException:
    # One message for every rejection: unknown, spent and expired tokens must not
    # be distinguishable to someone guessing.
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired enrollment token")


@router.post("/enroll", response_model=EnrollResponse)
async def enroll(
    body: EnrollRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EnrollResponse:
    """A machine introduces itself and collects what it needs to join.

    Everything it needs comes back in one response: the swarm join token for
    membership and the overlay network, a Docker server certificate signed by
    the cluster CA so the spawner can reach it, and the image names to pre-pull.

    The GPUs it reports are recorded but not yet placed in the pool — that waits
    for /enroll/complete, once the machine is actually reachable. A GPU listed
    before then would be handed to a user whose container cannot start.
    """
    try:
        enrollment, node = await nodes_svc.resolve_enrollment(db, body.token)
    except nodes_svc.NodeError as exc:
        raise _bad_token() from exc

    if not settings.swarm_worker_token or not settings.manager_advertise_addr:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "This Sahab is not set up to accept extra machines yet: no swarm "
                "join token is configured. Re-run scripts/bootstrap.sh on the "
                "control plane, which initialises the swarm and records the token."
            ),
        )

    hostname = body.hostname.strip()
    address = body.advertise_addr.strip()

    # The machine's real hostname replaces whatever placeholder the admin typed,
    # unless another node already answers to it.
    if hostname and hostname != node.name:
        clash = await db.execute(
            select(Node).where(Node.name == hostname, Node.id != node.id)
        )
        if clash.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Another machine is already registered as {hostname}.",
            )
        node.name = hostname

    node.address = address
    node.docker_port = body.docker_port
    node.metrics_url = nodes_svc.default_metrics_url(address)
    node.driver_version = body.driver_version
    node.docker_version = body.docker_version
    node.status = NodeStatus.enrolling
    if not node.display_name:
        node.display_name = hostname or address

    # Stash the reported GPUs on the enrollment log so /complete can register
    # them without the machine having to send the list twice.
    await nodes_svc.stash_reported_gpus(db, enrollment, [g.model_dump() for g in body.gpus])

    enrollment.status = EnrollmentStatus.running
    await nodes_svc.append_log(
        db,
        enrollment,
        f"[{datetime.now(tz=timezone.utc).isoformat()}] {hostname} ({address}) "
        f"requested enrollment with {len(body.gpus)} GPU(s)\n",
    )

    server_cert, server_key = node_certs.issue_server_cert(
        common_name=node.name, sans=[address, hostname, "localhost", "127.0.0.1"]
    )

    await db.commit()
    logger.info("Node %s (%s) enrolling", node.name, address)

    return EnrollResponse(
        node_id=node.id,
        node_name=node.name,
        network_name=settings.docker_network_name,
        swarm_join_token=settings.swarm_worker_token,
        manager_addr=settings.manager_advertise_addr,
        registry_addr=settings.registry_addr,
        ca_cert=node_certs.ca_cert_pem(),
        server_cert=server_cert,
        server_key=server_key,
        gpu_image=settings.workspace_gpu_image,
        cpu_image=settings.workspace_cpu_image,
        dcgm_port=nodes_svc.DCGM_PORT,
        node_exporter_port=nodes_svc.NODE_EXPORTER_PORT,
        cadvisor_port=nodes_svc.CADVISOR_PORT,
    )


@router.post("/enroll/complete", response_model=EnrollCompleteResponse)
async def enroll_complete(
    body: EnrollCompleteRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EnrollCompleteResponse:
    """The machine says it is ready; we check for ourselves before believing it.

    The GPUs only enter the pool once this side can actually open a mutually
    authenticated connection to the machine's Docker API. That is the same call
    the spawner will make, so a node that reaches 'ready' here is a node that can
    genuinely start a workspace.
    """
    try:
        enrollment, node = await nodes_svc.resolve_enrollment(db, body.token)
    except nodes_svc.NodeError as exc:
        raise _bad_token() from exc

    reachable, detail = await nodes_svc.ping_node(node)
    if not reachable:
        enrollment.status = EnrollmentStatus.failed
        await nodes_svc.append_log(
            db, enrollment, f"Docker API check failed: {detail}\n"
        )
        node.status = NodeStatus.unreachable
        node.unreachable_since = datetime.now(tz=timezone.utc)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"Sahab could not reach this machine's Docker API at "
                f"{nodes_svc.docker_base_url(node)}. Check that port "
                f"{node.docker_port} is open between the two machines. ({detail})"
            ),
        )

    gpus = await nodes_svc.take_reported_gpus(db, enrollment)
    added, updated = await nodes_svc.sync_node_gpus(db, node, gpus)

    node.status = NodeStatus.ready
    node.docker_version = detail or node.docker_version
    node.enrolled_at = node.enrolled_at or datetime.now(tz=timezone.utc)
    node.last_seen_at = datetime.now(tz=timezone.utc)
    node.unreachable_since = None

    enrollment.status = EnrollmentStatus.completed
    enrollment.used_at = datetime.now(tz=timezone.utc)
    await nodes_svc.append_log(
        db, enrollment, f"Enrolled: {added} GPU(s) added, {updated} updated. Node is ready.\n"
    )

    await db.commit()
    await nodes_svc.publish_node_map(db, settings)
    logger.info("Node %s ready with %d new GPU(s)", node.name, added)

    return EnrollCompleteResponse(
        node_id=node.id,
        node_name=node.name,
        status=node.status,
        gpus_registered=added + updated,
    )
